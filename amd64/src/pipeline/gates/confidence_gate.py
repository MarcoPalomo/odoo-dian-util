"""
Gate 1 — Confiance d'extraction.
Si un champ obligatoire est sous le seuil → document en HITL.
"""
from __future__ import annotations

import os

import structlog

from pipeline.models import RUTExtraction

log = structlog.get_logger()

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.92"))
MANDATORY_FIELDS = ("vat", "name")


def run(extraction: RUTExtraction) -> tuple[RUTExtraction, bool]:
    """
    Retourne (extraction, needs_hitl).
    needs_hitl=True si un champ obligatoire est absent ou sous le seuil.
    """
    reasons: list[str] = []

    for field_name in MANDATORY_FIELDS:
        field = getattr(extraction, field_name)
        if field is None or field.value is None:
            reasons.append(f"{field_name}=absent")
        elif field.confidence < CONFIDENCE_THRESHOLD:
            reasons.append(f"{field_name}.confidence={field.confidence:.2f} < {CONFIDENCE_THRESHOLD}")

    needs_hitl = bool(reasons)
    updated = extraction.model_copy(update={"needs_hitl": needs_hitl})

    if needs_hitl:
        log.warning(
            "confidence_gate_fail",
            doc_id=extraction.doc_id,
            reasons=reasons,
            threshold=CONFIDENCE_THRESHOLD,
        )
    else:
        log.info("confidence_gate_pass", doc_id=extraction.doc_id)

    return updated, needs_hitl
