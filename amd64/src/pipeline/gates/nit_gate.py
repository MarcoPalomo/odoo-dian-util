"""
Gate 2 — Validation du NIT (dígito de verificación DIAN).
Un NIT avec DV invalide est une erreur d'extraction — jamais accepté.
"""
from __future__ import annotations

import structlog

from pipeline.models import RUTExtraction
from pipeline.nit_validator import validate_nit

log = structlog.get_logger()


class NITValidationError(Exception):
    pass


def run(extraction: RUTExtraction) -> RUTExtraction:
    """
    Valide le DV du NIT extrait.
    Met à jour nit_dv_valid sur l'extraction.
    Lève NITValidationError si le NIT est invalide — le document va en DLQ, pas en HITL
    (un humain doit corriger la valeur extraite, pas bypasser la validation).
    """
    if extraction.vat is None or not extraction.vat.value:
        updated = extraction.model_copy(update={"nit_dv_valid": False})
        log.warning("nit_gate_no_nit", doc_id=extraction.doc_id)
        return updated

    nit_raw = extraction.vat.value
    dv_raw = extraction.nit_dv_extracted or ""

    # On reconstitue la chaîne NIT-DV pour la passer au validateur
    if dv_raw:
        full_nit = f"{nit_raw}-{dv_raw}"
    else:
        full_nit = nit_raw

    result = validate_nit(full_nit)

    updated = extraction.model_copy(update={"nit_dv_valid": result.is_valid})

    if result.is_valid:
        log.info("nit_gate_pass", doc_id=extraction.doc_id, nit=result.nit)
    else:
        log.error(
            "nit_gate_fail",
            doc_id=extraction.doc_id,
            nit_raw=nit_raw,
            dv_extracted=dv_raw,
            error=result.error,
        )
        raise NITValidationError(
            f"NIT invalide pour doc {extraction.doc_id}: {result.error}"
        )

    return updated
