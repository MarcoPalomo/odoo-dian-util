"""
Stockage des retries de pré-qualification différés.
Quand DIAN ou RUES sont indisponibles, on enregistre le contexte pour relancer
le lendemain à la même heure.

Backend : PostgreSQL (AUDIT_DB_DSN). No-op si la base n'est pas configurée.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

log = structlog.get_logger()


@dataclass
class PendingRetry:
    id: int
    nit: str
    partner_id: int
    lead_id: Optional[int]
    fuentes_fallidas: list[str]
    score_partiel: int
    semaforo_prev: str
    retry_after: datetime


class RetryStore:
    def __init__(self, dsn: str = ""):
        self._dsn = dsn or os.getenv("AUDIT_DB_DSN", "")
        self._enabled = bool(self._dsn)
        if not self._enabled:
            log.warning("retry_store_disabled", reason="AUDIT_DB_DSN non configuré")

    def _conn(self):
        import psycopg2
        return psycopg2.connect(self._dsn)

    def save(
        self,
        nit: str,
        partner_id: int,
        lead_id: Optional[int],
        fuentes_fallidas: list[str],
        score_partiel: int,
        semaforo_prev: str,
    ) -> None:
        """Enregistre un retry pour le lendemain à la même heure."""
        if not self._enabled:
            return

        retry_after = datetime.now(tz=timezone.utc) + timedelta(days=1)
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO prequal_retries
                        (nit, partner_id, lead_id, fuentes_fallidas,
                         score_partiel, semaforo_prev, retry_after)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (nit, partner_id, lead_id, fuentes_fallidas,
                     score_partiel, semaforo_prev, retry_after),
                )
            conn.commit()
            log.info("retry_saved", nit=nit, retry_after=retry_after.isoformat(),
                     fuentes=fuentes_fallidas)
        finally:
            conn.close()

    def fetch_due(self) -> list[PendingRetry]:
        """Retourne les retries dont l'heure est passée et non encore traités."""
        if not self._enabled:
            return []

        now = datetime.now(tz=timezone.utc)
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, nit, partner_id, lead_id, fuentes_fallidas,
                           score_partiel, semaforo_prev, retry_after
                    FROM prequal_retries
                    WHERE retry_after <= %s AND retried_at IS NULL
                    ORDER BY retry_after
                    """,
                    (now,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            PendingRetry(
                id=r[0], nit=r[1], partner_id=r[2], lead_id=r[3],
                fuentes_fallidas=list(r[4]), score_partiel=r[5],
                semaforo_prev=r[6], retry_after=r[7],
            )
            for r in rows
        ]

    def mark_done(self, retry_id: int) -> None:
        if not self._enabled:
            return

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE prequal_retries SET retried_at = NOW() WHERE id = %s",
                    (retry_id,),
                )
            conn.commit()
        finally:
            conn.close()
