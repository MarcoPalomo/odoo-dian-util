"""
Audit log PostgreSQL — source de vérité pour conformité Ley 1581 et dashboards Metabase.
Base séparée de l'instance Odoo.
"""
from __future__ import annotations

import os
from datetime import datetime

import psycopg2
import psycopg2.extras
import structlog

from pipeline.models import AuditEntry

log = structlog.get_logger()

AUDIT_DB_DSN = os.getenv("AUDIT_DB_DSN", "")


class AuditLog:
    def __init__(self, dsn: str = AUDIT_DB_DSN):
        self._dsn = dsn
        self._conn = None
        self._enabled = bool(dsn)
        if not self._enabled:
            log.warning("audit_log_disabled", reason="AUDIT_DB_DSN non configuré — logs non persistés")

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn)
        return self._conn

    def write(self, entry: AuditEntry) -> None:
        if not self._enabled:
            return
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipeline_audit_log (
                    doc_id, source, raw_s3_path, extraction_engine,
                    extraction_confidence, nit_extracted, nit_valid,
                    needs_hitl, hitl_operator, odoo_partner_id,
                    odoo_action, error_message, duration_ms, created_at
                ) VALUES (
                    %(doc_id)s, %(source)s, %(raw_s3_path)s, %(extraction_engine)s,
                    %(extraction_confidence)s, %(nit_extracted)s, %(nit_valid)s,
                    %(needs_hitl)s, %(hitl_operator)s, %(odoo_partner_id)s,
                    %(odoo_action)s, %(error_message)s, %(duration_ms)s, %(created_at)s
                )
                """,
                {
                    "doc_id": entry.doc_id,
                    "source": entry.source.value,
                    "raw_s3_path": entry.raw_s3_path,
                    "extraction_engine": entry.extraction_engine,
                    "extraction_confidence": entry.extraction_confidence,
                    "nit_extracted": entry.nit_extracted,
                    "nit_valid": entry.nit_valid,
                    "needs_hitl": entry.needs_hitl,
                    "hitl_operator": entry.hitl_operator,
                    "odoo_partner_id": entry.odoo_partner_id,
                    "odoo_action": entry.odoo_action.value if entry.odoo_action else None,
                    "error_message": entry.error_message,
                    "duration_ms": entry.duration_ms,
                    "created_at": entry.created_at or datetime.utcnow(),
                },
            )
        conn.commit()
        log.info(
            "audit_written",
            doc_id=entry.doc_id,
            action=entry.odoo_action,
            duration_ms=entry.duration_ms,
        )

    def close(self) -> None:
        if self._enabled and self._conn and not self._conn.closed:
            self._conn.close()
