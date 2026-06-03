#!/usr/bin/env python3
"""
Ingestion depuis le module Documents d'Odoo.

Workflow :
  1. Dépose un PDF RUT dans le workspace "RUTs Clientes" (id=196) dans Odoo Documents
  2. Ce script détecte les nouveaux PDFs (sans tag "Validated")
  3. Lance le pipeline complet (extraction → validation → upsert Odoo)
  4. Met à jour le document : partner_id + tag "Validated" ou "To Validate" (HITL)

Usage :
  python scripts/ingest_from_documents.py             # traite tous les en attente
  python scripts/ingest_from_documents.py --watch     # boucle toutes les 30s
  python scripts/ingest_from_documents.py --dry-run   # sans écriture Odoo/MinIO
"""
from __future__ import annotations

import base64
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import click
import structlog
from dotenv import load_dotenv

load_dotenv()

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

from pipeline.audit_log import AuditLog
from pipeline.models import DocumentSource
from pipeline.odoo_client import OdooClient
from pipeline.runner import Pipeline

log = structlog.get_logger()

# ── Constantes instance industriaspico ────────────────────────────────────────
RUT_FOLDER_ID  = 196   # workspace "RUTs Clientes" créé le 2026-06-02
TAG_INBOX      = 1     # documents.tag "Inbox"
TAG_TO_VALIDATE = 2    # documents.tag "To Validate" — HITL requis
TAG_VALIDATED  = 3     # documents.tag "Validated" — traitement réussi
DOC_MODEL      = "documents.document"


class DocumentsIngester:
    def __init__(self, odoo: OdooClient, dry_run: bool = False):
        self._odoo = odoo
        self._dry_run = dry_run

    def _call(self, model: str, method: str, args, kwargs=None):
        return self._odoo._call(model, method, args, kwargs or {})

    def fetch_pending(self) -> list[dict]:
        """Retourne les PDFs dans RUTs Clientes sans tag Validated ni To Validate."""
        return self._call(
            DOC_MODEL, "search_read",
            [[
                ["folder_id", "=", RUT_FOLDER_ID],
                ["mimetype", "ilike", "pdf"],
                ["tag_ids", "not in", [TAG_VALIDATED, TAG_TO_VALIDATE]],
            ]],
            {"fields": ["id", "name", "datas", "tag_ids", "partner_id", "file_size"]},
        )

    def download_pdf(self, doc: dict, tmp_dir: Path) -> Path:
        """Décode le contenu base64 et écrit le PDF dans un fichier temporaire."""
        raw = base64.b64decode(doc["datas"])
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in doc["name"])
        pdf_path = tmp_dir / safe_name
        pdf_path.write_bytes(raw)
        log.info("document_downloaded", doc_id=doc["id"], name=doc["name"], bytes=len(raw))
        return pdf_path

    def mark_processing(self, doc_id: int) -> None:
        """Ajoute le tag Inbox pour signaler que le document est en cours."""
        if not self._dry_run:
            self._call(DOC_MODEL, "write",
                [[doc_id], {"tag_ids": [(4, TAG_INBOX)]}])

    def mark_validated(self, doc_id: int, partner_id: int) -> None:
        """Tag Validated + lien vers le contact créé/mis à jour."""
        if not self._dry_run:
            self._call(DOC_MODEL, "write", [[doc_id], {
                "tag_ids": [
                    (3, TAG_INBOX),        # retirer Inbox
                    (3, TAG_TO_VALIDATE),  # retirer To Validate au cas où
                    (4, TAG_VALIDATED),    # ajouter Validated
                ],
                "partner_id": partner_id,
            }])
            log.info("document_marked_validated", doc_id=doc_id, partner_id=partner_id)

    def mark_hitl(self, doc_id: int) -> None:
        """Tag To Validate — l'humain doit intervenir dans l'interface HITL."""
        if not self._dry_run:
            self._call(DOC_MODEL, "write", [[doc_id], {
                "tag_ids": [
                    (3, TAG_INBOX),
                    (4, TAG_TO_VALIDATE),
                ],
            }])
            log.info("document_marked_hitl", doc_id=doc_id)

    def mark_failed(self, doc_id: int, error: str) -> None:
        """Retire Inbox, laisse sans tag validé — visible dans le workspace."""
        if not self._dry_run:
            self._call(DOC_MODEL, "write", [[doc_id], {
                "tag_ids": [(3, TAG_INBOX)],
            }])
        log.error("document_failed", doc_id=doc_id, error=error)

    def reset_all(self) -> int:
        """Retire les tags Validated et To Validate de tous les docs du workspace."""
        docs = self._call(
            DOC_MODEL, "search_read",
            [[
                ["folder_id", "=", RUT_FOLDER_ID],
                ["mimetype", "ilike", "pdf"],
                ["tag_ids", "in", [TAG_VALIDATED, TAG_TO_VALIDATE]],
            ]],
            {"fields": ["id", "name"]},
        )
        if not docs:
            return 0
        ids = [d["id"] for d in docs]
        self._call(DOC_MODEL, "write", [ids, {
            "tag_ids": [
                (3, TAG_VALIDATED),
                (3, TAG_TO_VALIDATE),
                (3, TAG_INBOX),
            ],
        }])
        for d in docs:
            log.info("document_reset", doc_id=d["id"], name=d["name"])
        return len(ids)

    def post_chatter_note(self, doc_id: int, message: str) -> None:
        if not self._dry_run:
            self._call(DOC_MODEL, "message_post", [[doc_id]], {
                "body": message,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_note",
            })


def process_all(ingester: DocumentsIngester, pipeline: Pipeline) -> int:
    """Traite tous les documents en attente. Retourne le nombre traité."""
    pending = ingester.fetch_pending()

    if not pending:
        log.info("no_pending_documents", folder_id=RUT_FOLDER_ID)
        return 0

    log.info("pending_documents_found", count=len(pending))

    processed = 0
    with tempfile.TemporaryDirectory(prefix="odoo_docs_") as tmp:
        tmp_dir = Path(tmp)

        for doc in pending:
            doc_id = doc["id"]
            name = doc["name"]
            log.info("processing_document", doc_id=doc_id, name=name, size=doc["file_size"])

            ingester.mark_processing(doc_id)

            try:
                pdf_path = ingester.download_pdf(doc, tmp_dir)

                # s3_path pointe vers Odoo Documents — bypasse l'archivage MinIO
                odoo_ref = f"odoo://documents.document/{doc_id}"
                result = pipeline.process(
                    pdf_path=pdf_path,
                    source=DocumentSource.UPLOAD,
                    is_cliente=True,
                    s3_path=odoo_ref,
                )

                if result.needs_hitl:
                    ingester.mark_hitl(doc_id)
                    ingester.post_chatter_note(
                        doc_id,
                        f"⚠️ Revisión manual requerida — confianza de extracción baja. "
                        f"doc_id: {result.doc_id}"
                    )
                    log.warning("document_needs_hitl", doc_id=doc_id, odoo_doc=doc_id)

                elif result.error:
                    ingester.mark_failed(doc_id, result.error)
                    ingester.post_chatter_note(
                        doc_id,
                        f"❌ Error en el pipeline: {result.error}"
                    )

                else:
                    ingester.mark_validated(doc_id, result.odoo_partner_id)
                    ingester.post_chatter_note(
                        doc_id,
                        f"✅ RUT procesado — contacto {'creado' if result.odoo_action.value == 'created' else 'actualizado'} "
                        f"(partner_id={result.odoo_partner_id}). "
                        f"doc_id: {result.doc_id}"
                    )
                    log.info("document_processed",
                             doc_id=doc_id,
                             partner_id=result.odoo_partner_id,
                             action=result.odoo_action)

                processed += 1

            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                ingester.mark_failed(doc_id, error_msg)
                log.exception("document_unexpected_error", doc_id=doc_id, error=error_msg)

    return processed


@click.command()
@click.option("--dry-run", is_flag=True, default=False, help="Sans écriture dans Odoo ni MinIO")
@click.option("--watch", is_flag=True, default=False, help="Boucle toutes les 30 secondes")
@click.option("--interval", default=30, help="Intervalle en secondes pour --watch (défaut: 30)")
@click.option("--proveedor", is_flag=True, default=False, help="Marquer comme fournisseur")
@click.option("--reset", is_flag=True, default=False, help="Réinitialiser les tags avant de traiter")
def main(dry_run: bool, watch: bool, interval: int, proveedor: bool, reset: bool):
    """Ingère les PDFs RUT depuis le workspace 'RUTs Clientes' dans Odoo Documents."""

    from unittest.mock import MagicMock

    odoo = OdooClient() if not dry_run else MagicMock()
    # MinIO non requis ici : le document est déjà dans Odoo Documents.
    # On passe s3_path=odoo://... au pipeline pour bypasser l'archivage.
    storage = MagicMock()
    audit = AuditLog()

    pipeline = Pipeline(storage=storage, odoo=odoo, audit=audit, dry_run=dry_run)
    ingester = DocumentsIngester(odoo=OdooClient() if not dry_run else MagicMock(), dry_run=dry_run)

    if reset:
        n_reset = ingester.reset_all()
        click.echo(f"  {n_reset} document(s) réinitialisé(s)")

    if watch:
        log.info("watch_mode_started", interval_s=interval, folder_id=RUT_FOLDER_ID)
        while True:
            n = process_all(ingester, pipeline)
            if n:
                click.echo(f"  {n} document(s) traité(s)")
            time.sleep(interval)
    else:
        n = process_all(ingester, pipeline)
        click.echo(f"\n  {n} document(s) traité(s)")


if __name__ == "__main__":
    main()
