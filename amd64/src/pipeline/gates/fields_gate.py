"""
Gate 3 — Validation des champs obligatoires et construction du ValidatedRUT.
Dernière gate avant l'appel Odoo.
"""
from __future__ import annotations

import structlog

from pipeline.models import RUTExtraction, ValidatedRUT

log = structlog.get_logger()

MANDATORY_FIELDS = ("vat", "name")


class MandatoryFieldError(Exception):
    pass


def run(extraction: RUTExtraction) -> ValidatedRUT:
    """
    Vérifie les champs obligatoires et construit un ValidatedRUT propre.
    Lève MandatoryFieldError si un champ obligatoire est absent.
    """
    missing = [
        f for f in MANDATORY_FIELDS
        if not getattr(extraction, f) or not getattr(extraction, f).value
    ]
    if missing:
        msg = f"Champs obligatoires manquants pour doc {extraction.doc_id}: {missing}"
        log.error("fields_gate_fail", doc_id=extraction.doc_id, missing=missing)
        raise MandatoryFieldError(msg)

    def val(field_name: str) -> str | None:
        field = getattr(extraction, field_name, None)
        return field.value if field else None

    validated = ValidatedRUT(
        doc_id=extraction.doc_id,
        vat=extraction.vat.value,
        name=extraction.name.value,
        l10n_latam_identification_type_id=extraction.l10n_latam_identification_type_id,
        l10n_co_edi_fiscal_regimen=val("l10n_co_edi_fiscal_regimen"),
        l10n_co_edi_commercial_name=val("l10n_co_edi_commercial_name"),
        email_dian=val("email_dian"),
        street=val("street"),
        city=val("city"),
        extraction_engine=extraction.extraction_engine,
        extraction_confidence=extraction.extraction_confidence,
    )

    log.info(
        "fields_gate_pass",
        doc_id=extraction.doc_id,
        vat=validated.vat,
        name=validated.name,
    )
    return validated
