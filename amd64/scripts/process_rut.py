#!/usr/bin/env python3
"""
CLI — traiter un RUT PDF manuellement à travers le pipeline complet.
Usage: python scripts/process_rut.py path/to/rut.pdf [--dry-run] [--proveedor] [--queue]
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import click
from dotenv import load_dotenv

load_dotenv()

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

from pipeline.audit_log import AuditLog
from pipeline.models import DocumentSource
from pipeline.odoo_client import OdooClient
from pipeline.queue_client import QueueClient
from pipeline.runner import Pipeline
from pipeline.storage_client import StorageClient

log = structlog.get_logger()


@click.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=False, help="Ne pas écrire dans Odoo ni MinIO")
@click.option("--proveedor", is_flag=True, default=False, help="Marquer comme fournisseur (défaut: client)")
@click.option("--source", default="upload", type=click.Choice(["upload", "email", "whatsapp"]))
@click.option("--queue", "use_queue", is_flag=True, default=False, help="Envoyer dans la queue Redis au lieu de traiter directement")
def main(pdf_path: Path, dry_run: bool, proveedor: bool, source: str, use_queue: bool):
    """Traite un RUT PDF à travers le pipeline complet."""

    if use_queue:
        _enqueue(pdf_path, source=source, is_cliente=not proveedor)
        return

    log.info("cli_start", pdf=str(pdf_path), dry_run=dry_run, source=source)

    storage = StorageClient() if not dry_run else None
    odoo = OdooClient() if not dry_run else None
    audit = AuditLog()

    # En dry-run, on crée des clients factices via le pipeline en mode dry_run
    if dry_run:
        from unittest.mock import MagicMock
        storage = MagicMock()
        odoo = MagicMock()

    pipeline = Pipeline(storage=storage, odoo=odoo, audit=audit, dry_run=dry_run)

    result = pipeline.process(
        pdf_path=pdf_path,
        source=DocumentSource(source),
        is_cliente=not proveedor,
    )

    click.echo("")
    click.echo("─" * 60)
    click.echo(f"  doc_id      : {result.doc_id}")
    click.echo(f"  s3_path     : {result.s3_path}")
    click.echo(f"  needs_hitl  : {result.needs_hitl}")
    click.echo(f"  odoo_action : {result.odoo_action}")
    click.echo(f"  partner_id  : {result.odoo_partner_id}")
    click.echo(f"  duration_ms : {result.duration_ms}")
    if result.error:
        click.echo(f"  error       : {result.error}", err=True)
    click.echo("─" * 60)

    sys.exit(1 if result.error else 0)


def _enqueue(pdf_path: Path, source: str, is_cliente: bool) -> None:
    """Archive le PDF dans MinIO puis publie un message dans documents:incoming."""
    doc_id = str(uuid.uuid4())
    storage = StorageClient()
    s3_path = storage.archive(doc_id, pdf_path, source=source)

    queue = QueueClient()
    msg_id = queue.publish(
        QueueClient.STREAM_INCOMING,
        {
            "doc_id": doc_id,
            "s3_path": s3_path,
            "source": source,
            "is_cliente": str(is_cliente).lower(),
            "submitted_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    )
    queue.close()

    click.echo("")
    click.echo("─" * 60)
    click.echo(f"  doc_id : {doc_id}")
    click.echo(f"  s3_path: {s3_path}")
    click.echo(f"  msg_id : {msg_id}")
    click.echo("  estado : encolado")
    click.echo("─" * 60)


if __name__ == "__main__":
    main()
