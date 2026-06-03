"""
Orchestrateur principal du pipeline Sprint 1.
Séquence : archive → extrait → gate confiance → gate NIT → gate champs → Odoo → audit
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from pipeline.audit_log import AuditLog
from pipeline.extraction.pdfplumber_extractor import extract_rut
from pipeline.fiscal_intelligence import extract_fiscal_profile
from pipeline.prequalification import run_prequalification
from pipeline.retry_store import RetryStore
from pipeline.gates import confidence_gate, fields_gate, nit_gate
from pipeline.gates.nit_gate import NITValidationError
from pipeline.gates.fields_gate import MandatoryFieldError
from pipeline.models import AuditEntry, DocumentSource, OdooAction, RUTExtraction
from pipeline.odoo_client import OdooClient
from pipeline.storage_client import StorageClient

log = structlog.get_logger()


@dataclass
class PipelineResult:
    doc_id: str
    s3_path: Optional[str]
    odoo_partner_id: Optional[int]
    odoo_action: Optional[OdooAction]
    needs_hitl: bool
    error: Optional[str]
    duration_ms: int
    extraction: Optional[RUTExtraction] = None  # rempli si needs_hitl=True, pour routage HITL


class Pipeline:
    def __init__(
        self,
        storage: StorageClient,
        odoo: OdooClient,
        audit: AuditLog,
        dry_run: bool = False,
        retry_store: Optional[RetryStore] = None,
    ):
        self._storage = storage
        self._odoo = odoo
        self._audit = audit
        self._dry_run = dry_run
        self._retry_store = retry_store or RetryStore()

    def process(
        self,
        pdf_path: Path,
        source: DocumentSource = DocumentSource.UPLOAD,
        is_cliente: bool = True,
        doc_id: Optional[str] = None,
        s3_path: Optional[str] = None,        # pré-archivé par le worker → skip archive
        hitl_operator: Optional[str] = None,  # opérateur HITL → audit log
    ) -> PipelineResult:
        if doc_id is None:
            doc_id = str(uuid.uuid4())

        start_ms = time.monotonic_ns() // 1_000_000
        extraction: Optional[RUTExtraction] = None
        partner_id: Optional[int] = None
        action: Optional[OdooAction] = None
        needs_hitl = False
        error: Optional[str] = None

        try:
            # ── 1. Archivage avant tout traitement (règle fondamentale) ──────
            if s3_path is not None:
                log.info("archive_skipped_pre_archived", doc_id=doc_id, s3_path=s3_path)
            elif not self._dry_run:
                s3_path = self._storage.archive(
                    doc_id, pdf_path, source=source.value
                )
            else:
                s3_path = f"dry-run://{pdf_path.name}"
                log.info("dry_run_skip_archive", path=str(pdf_path))

            # ── 2. Extraction ────────────────────────────────────────────────
            extraction = extract_rut(pdf_path, doc_id=doc_id)

            # ── 3. Gate confiance ────────────────────────────────────────────
            extraction, needs_hitl = confidence_gate.run(extraction)
            if needs_hitl:
                log.warning("pipeline_hitl_required", doc_id=doc_id)
                self._write_audit(
                    extraction, source, s3_path,
                    needs_hitl=True, start_ms=start_ms,
                    hitl_operator=hitl_operator,
                )
                return PipelineResult(
                    doc_id=doc_id, s3_path=s3_path,
                    odoo_partner_id=None, odoo_action=None,
                    needs_hitl=True, error=None,
                    duration_ms=int(time.monotonic_ns() // 1_000_000 - start_ms),
                    extraction=extraction,
                )

            # ── 4. Gate NIT ──────────────────────────────────────────────────
            extraction = nit_gate.run(extraction)

            # ── 5. Gate champs obligatoires + construction ValidatedRUT ──────
            validated = fields_gate.run(extraction)

            # ── 6. Upsert Odoo + pré-qualification ──────────────────────────
            if not self._dry_run:
                partner_id, action = self._odoo.upsert_partner(
                    validated, doc_id=doc_id, s3_path=s3_path, is_cliente=is_cliente
                )
                self._run_postprocess(extraction, validated, partner_id, source, doc_id)
            else:
                log.info("dry_run_skip_odoo", vat=validated.vat, name=validated.name)
                action = OdooAction.SKIPPED

        except NITValidationError as exc:
            error = str(exc)
            action = OdooAction.FAILED
            log.error("pipeline_nit_error", doc_id=doc_id, error=error)

        except MandatoryFieldError as exc:
            error = str(exc)
            action = OdooAction.FAILED
            log.error("pipeline_fields_error", doc_id=doc_id, error=error)

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            action = OdooAction.FAILED
            log.exception("pipeline_unexpected_error", doc_id=doc_id, error=error)

        finally:
            if extraction or error:
                self._write_audit(
                    extraction, source, s3_path,
                    needs_hitl=needs_hitl,
                    partner_id=partner_id,
                    action=action,
                    error=error,
                    start_ms=start_ms,
                    hitl_operator=hitl_operator,
                )

        return PipelineResult(
            doc_id=doc_id or "unknown",
            s3_path=s3_path,
            odoo_partner_id=partner_id,
            odoo_action=action,
            needs_hitl=needs_hitl,
            error=error,
            duration_ms=int(time.monotonic_ns() // 1_000_000 - start_ms),
        )

    def _run_postprocess(
        self,
        extraction: RUTExtraction,
        validated,
        partner_id: int,
        source: DocumentSource,
        doc_id: str,
    ) -> None:
        """Perfil fiscal (chatter) + pré-qualification + retry différé si sources down."""
        profile = extract_fiscal_profile(extraction.raw_text or "")
        note_html = profile.as_html(
            nit=validated.vat,
            dv=extraction.nit_dv_extracted or "?",
            source=source.value,
            doc_id=doc_id,
        )
        self._odoo.post_import_note(partner_id, note_html)

        prequal = run_prequalification(validated.vat, profile)
        lead_id = self._odoo.create_prequalification_lead(
            partner_id=partner_id,
            partner_name=validated.name,
            prequal_html=prequal.as_html(),
            semaforo=prequal.semaforo,
        )
        log.info(
            "prequalification_result",
            nit=validated.vat,
            semaforo=prequal.semaforo,
            score=prequal.score,
            dian_estado=prequal.dian_estado,
            rues_capital=prequal.rues_capital,
        )
        if prequal.fuentes_fallidas:
            self._retry_store.save(
                nit=validated.vat,
                partner_id=partner_id,
                lead_id=lead_id,
                fuentes_fallidas=prequal.fuentes_fallidas,
                score_partiel=prequal.score,
                semaforo_prev=prequal.semaforo,
            )
            log.info("retry_scheduled", nit=validated.vat, fuentes=prequal.fuentes_fallidas)

    def _write_audit(
        self,
        extraction: Optional[RUTExtraction],
        source: DocumentSource,
        s3_path: Optional[str],
        needs_hitl: bool,
        partner_id: Optional[int] = None,
        action: Optional[OdooAction] = None,
        error: Optional[str] = None,
        start_ms: int = 0,
        hitl_operator: Optional[str] = None,
    ) -> None:
        duration_ms = int(time.monotonic_ns() // 1_000_000 - start_ms)
        entry = AuditEntry(
            doc_id=extraction.doc_id if extraction else "unknown",
            source=source,
            raw_s3_path=s3_path,
            extraction_engine=extraction.extraction_engine.value if extraction else None,
            extraction_confidence=extraction.extraction_confidence if extraction else None,
            nit_extracted=extraction.vat.value if extraction and extraction.vat else None,
            nit_valid=extraction.nit_dv_valid if extraction else None,
            needs_hitl=needs_hitl,
            hitl_operator=hitl_operator,
            odoo_partner_id=partner_id,
            odoo_action=action,
            error_message=error,
            duration_ms=duration_ms,
        )
        try:
            self._audit.write(entry)
        except Exception as exc:
            log.error("audit_write_failed", error=str(exc))
