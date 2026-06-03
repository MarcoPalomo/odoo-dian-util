#!/usr/bin/env python3
"""
Retry différé des pré-qualifications avec sources DIAN/RUES manquantes.

Planifié pour tourner chaque jour à la même heure (via cron ou make prequal-retry).
Recharge uniquement les sources qui avaient échoué, met à jour la lead CRM si
le semáforo change.

Usage :
  python scripts/retry_prequalification.py
  make prequal-retry
"""
from __future__ import annotations

import os
import sys
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

from pipeline.odoo_client import OdooClient
from pipeline.prequalification import (
    _apply_dian_score,
    _apply_rues_score,
    _check_dian_estado,
    _check_rues,
    _determine_semaforo,
)
from pipeline.retry_store import RetryStore

log = structlog.get_logger()


def _retry_one(retry, odoo: OdooClient, store: RetryStore) -> str:
    """Rejoue les sources manquantes pour un retry. Retourne le nouveau semáforo."""
    score = retry.score_partiel
    positivos: list[str] = []
    negativos: list[str] = []
    fuentes_fallidas: list[str] = []

    if "DIAN estado RUT" in retry.fuentes_fallidas:
        dian_estado = _check_dian_estado(retry.nit)
        score = _apply_dian_score(dian_estado, score, positivos, negativos, fuentes_fallidas)
    else:
        dian_estado = None

    if "RUES Confecámaras" in retry.fuentes_fallidas:
        rues_capital, rues_estado = _check_rues(retry.nit)
        score = _apply_rues_score(rues_capital, rues_estado, score, positivos, negativos, fuentes_fallidas)

    score = max(0, min(100, score))
    semaforo_new, recomendacion = _determine_semaforo(score, negativos, fuentes_fallidas)

    sources_still_down = len(fuentes_fallidas)
    log.info(
        "retry_result",
        nit=retry.nit,
        semaforo_prev=retry.semaforo_prev,
        semaforo_new=semaforo_new,
        score=score,
        sources_still_down=sources_still_down,
    )

    if retry.lead_id:
        from pipeline.prequalification import PrequalResult
        prequal_updated = PrequalResult(
            nit=retry.nit,
            semaforo=semaforo_new,
            score=score,
            dian_estado=dian_estado,
            signals_positivos=positivos,
            signals_negativos=negativos,
            fuentes_fallidas=fuentes_fallidas,
            recomendacion=recomendacion,
        )
        odoo.update_lead_prequal(
            lead_id=retry.lead_id,
            partner_name=f"NIT {retry.nit}",
            prequal_html=prequal_updated.as_html(),
            semaforo_prev=retry.semaforo_prev,
            semaforo_new=semaforo_new,
        )

    store.mark_done(retry.id)

    # Si des sources sont encore down, on replanifie un nouveau retry
    if fuentes_fallidas and retry.lead_id:
        store.save(
            nit=retry.nit,
            partner_id=retry.partner_id,
            lead_id=retry.lead_id,
            fuentes_fallidas=fuentes_fallidas,
            score_partiel=score,
            semaforo_prev=semaforo_new,
        )
        log.info("retry_rescheduled", nit=retry.nit, fuentes=fuentes_fallidas)

    return semaforo_new


@click.command()
def main():
    """Relance les pré-qualifications en attente (sources DIAN/RUES down hier)."""
    dsn = os.getenv("AUDIT_DB_DSN", "")
    store = RetryStore(dsn=dsn)

    if not store._enabled:
        click.echo("AUDIT_DB_DSN non configuré — aucun retry possible.", err=True)
        sys.exit(1)

    pending = store.fetch_due()
    if not pending:
        click.echo("  Aucun retry en attente.")
        return

    click.echo(f"  {len(pending)} retry(s) à traiter...")
    odoo = OdooClient()

    ok = changed = rescheduled = 0
    for retry in pending:
        semaforo_new = _retry_one(retry, odoo, store)
        ok += 1
        if semaforo_new != retry.semaforo_prev:
            changed += 1

    click.echo(f"  Traités : {ok} | Semáforo changé : {changed}")


if __name__ == "__main__":
    main()
