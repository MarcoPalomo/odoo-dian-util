"""
Extraction des champs d'un RUT colombien (PDF natif DIAN) avec pdfplumber.

Format DIAN : tableau avec champs numérotés (35. Razón social, 42. Correo...).
Les chiffres du NIT sont séparés par des espaces dans les cellules du tableau.
Ex: "9 0 0 5 7 9 9 3 0  5  Impuestos y Aduanas de Bucaramanga  4"
     └── NIT digits ──┘ DV  └── dirección seccional ──────────┘ buzón
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional

import pdfplumber
import structlog

from pipeline.models import ExtractionEngine, FieldExtraction, RUTExtraction

log = structlog.get_logger()

# ── Patterns basés sur les numéros de champ DIAN ─────────────────────────────

_RE_NIT_HEADER = re.compile(
    r"N[úu]mero\s+de\s+Identificaci[óo]n\s+Tributaria[^\n]*\n"
    r"\s*((?:\d\s+){6,14}\d)",
    re.IGNORECASE,
)

# Champs textuels numérotés — valeur sur la ligne suivant le label
_RE_RAZON_SOCIAL     = re.compile(r"35\.\s*Raz[oó]n\s+[Ss]ocial[^\n]*\n\s*(.+)", re.IGNORECASE)
_RE_NOMBRE_COMERCIAL = re.compile(r"36\.\s*Nombre\s+[Cc]omercial[^\n]*\n\s*(.+)", re.IGNORECASE)
_RE_DIRECCION        = re.compile(r"41\.\s*Direcci[oó]n\s+[Pp]rincipal[^\n]*\n\s*(.+)", re.IGNORECASE)

# Persona natural — champs 31 (primer apellido) + 32 (segundo) + 33 (primer nombre) + 34 (otros)
_RE_PRIMER_APELLIDO  = re.compile(r"31\.\s*Primer\s+apellido[^\n]*\n\s*(.+)", re.IGNORECASE)
_RE_SEGUNDO_APELLIDO = re.compile(r"32\.\s*Segundo\s+apellido[^\n]*\n\s*(.+)", re.IGNORECASE)
_RE_PRIMER_NOMBRE    = re.compile(r"33\.\s*Primer\s+nombre[^\n]*\n\s*(.+)", re.IGNORECASE)
_RE_OTROS_NOMBRES    = re.compile(r"34\.\s*Otros\s+nombres[^\n]*\n\s*(.+)", re.IGNORECASE)

# Libellé de formulaire : valeur commençant par "NN. " → faux positif à rejeter
_RE_FORM_LABEL = re.compile(r"^\d+\.\s")

# Email sur la même ligne que le label
_RE_EMAIL = re.compile(
    r"42\.\s*Correo\s+[Ee]lectr[oó]nico\s+([\w.+-]+@[\w.-]+\.\w+)",
    re.IGNORECASE,
)

# Ciudad : dernière séquence de mots avant les chiffres de fin de ligne
# Format : "COLOMBIA 1 6 9 Santander 6 8 Bucaramanga 0 0 1"
_RE_TIPO_CONTRIBUYENTE = re.compile(r"24\.[^\n]*\n\s*(.+)", re.IGNORECASE)

_RE_LOCATION_HEADER = re.compile(r"38\.\s*Pa[íi]s[^\n]*\n\s*(.+)", re.IGNORECASE)
_RE_CITY_IN_ROW = re.compile(
    r"([A-ZÁÉÍÓÚÑA-Z][a-záéíóúña-z]+(?:\s+[A-ZÁÉÍÓÚÑA-Z][a-záéíóúña-z]+)*)"
    r"(?:\s+\d)+\s*$"
)

# Régimen fiscal — codes Odoo l10n_co_edi (vérifiés sur l'instance) :
#   '48' = IVA  |  '04' = INC  |  'ZA' = IVA+INC  |  '49' = No Aplica
# Détection via les codes de responsabilité du RUT (champ 53).
_RE_RESP_IVA = re.compile(r"\b48\s*-")
_RE_RESP_INC = re.compile(r"\b04\s*-")


def _clean(val: str) -> str:
    return re.sub(r"\s+", " ", val.strip())


def _extract_nit(text: str) -> tuple[Optional[FieldExtraction], Optional[str]]:
    """
    Extrait NIT et DV depuis la séquence de chiffres espace-séparés du tableau DIAN.
    Convention : dernier chiffre = DV, le reste = NIT.
    """
    m = _RE_NIT_HEADER.search(text)
    if m:
        all_digits = re.sub(r"\s+", "", m.group(1))
        if len(all_digits) >= 7:
            return FieldExtraction(value=all_digits[:-1], confidence=1.0), all_digits[-1]
    return FieldExtraction(value=None, confidence=0.0), None


def _extract_city(text: str) -> FieldExtraction:
    m = _RE_LOCATION_HEADER.search(text)
    if not m:
        return FieldExtraction(value=None, confidence=0.0)
    m_city = _RE_CITY_IN_ROW.search(m.group(1))
    if m_city:
        return FieldExtraction(value=_clean(m_city.group(1)), confidence=1.0)
    return FieldExtraction(value=None, confidence=0.0)


def _extract_regimen(text: str) -> Optional[FieldExtraction]:
    """
    Déduit le régime fiscal depuis les codes de responsabilité (champ 53 du RUT).
    Les codes correspondent directement aux valeurs du champ Odoo l10n_co_edi_fiscal_regimen.
    """
    has_iva = bool(_RE_RESP_IVA.search(text))
    has_inc = bool(_RE_RESP_INC.search(text))
    if has_iva and has_inc:
        return FieldExtraction(value="ZA", confidence=1.0)
    if has_iva:
        return FieldExtraction(value="48", confidence=1.0)
    if has_inc:
        return FieldExtraction(value="04", confidence=1.0)
    return FieldExtraction(value="49", confidence=0.8)  # No Aplica par défaut


def _extract_name(text: str) -> FieldExtraction:
    """Route vers champ 35 (jurídica) ou 31-34 (natural) selon le champ 24."""
    tipo = ""
    m = _RE_TIPO_CONTRIBUYENTE.search(text)
    if m:
        tipo = _clean(m.group(1)).lower()

    if "natural" in tipo:
        return _extract_persona_natural_name(text)
    if tipo:  # jurídica ou autre type connu
        return _field(text, _RE_RAZON_SOCIAL)
    # champ 24 non trouvé → fallback heuristique
    name = _field(text, _RE_RAZON_SOCIAL)
    return name if name.value else _extract_persona_natural_name(text)


def _extract_persona_natural_name(text: str) -> FieldExtraction:
    """Construit le nom complet depuis les champs 31-34 (persona natural).

    pdfplumber collapse souvent les 4 colonnes en une seule ligne, ce qui fait
    que chaque regex capture la même chaîne complète. La déduplication évite
    les répétitions sans perdre d'information.
    """
    seen: set[str] = set()
    parts: list[str] = []
    for pattern in (_RE_PRIMER_APELLIDO, _RE_SEGUNDO_APELLIDO, _RE_PRIMER_NOMBRE, _RE_OTROS_NOMBRES):
        m = pattern.search(text)
        if m:
            val = _clean(m.group(1))
            if val and not _RE_FORM_LABEL.match(val) and val not in seen:
                seen.add(val)
                parts.append(val)
    if not parts:
        return FieldExtraction(value=None, confidence=0.0)
    return FieldExtraction(value=" ".join(parts), confidence=1.0)


def _field(text: str, pattern: re.Pattern) -> FieldExtraction:
    m = pattern.search(text)
    if not m:
        return FieldExtraction(value=None, confidence=0.0)
    value = _clean(m.group(1))
    if not value or _RE_FORM_LABEL.match(value):
        return FieldExtraction(value=None, confidence=0.0)
    return FieldExtraction(value=value, confidence=1.0)


def extract_rut(pdf_path: Path, doc_id: Optional[str] = None) -> RUTExtraction:
    """Extrait les champs d'un RUT DIAN depuis un PDF natif."""
    if doc_id is None:
        doc_id = str(uuid.uuid4())

    log.info("extraction_start", doc_id=doc_id, path=str(pdf_path), engine="pdfplumber")

    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

    if not full_text.strip():
        log.warning("extraction_empty_text", doc_id=doc_id)
        return RUTExtraction(
            doc_id=doc_id,
            extraction_engine=ExtractionEngine.PDFPLUMBER,
            extraction_confidence=0.0,
            needs_hitl=True,
            raw_text="",
        )

    nit_field, dv_extracted = _extract_nit(full_text)
    name_field              = _extract_name(full_text)
    comercial_field         = _field(full_text, _RE_NOMBRE_COMERCIAL)
    street_field            = _field(full_text, _RE_DIRECCION)
    city_field              = _extract_city(full_text)
    email_field             = _field(full_text, _RE_EMAIL)
    regimen_field           = _extract_regimen(full_text)

    mandatory_scores = [
        nit_field.confidence if nit_field else 0.0,
        name_field.confidence if name_field else 0.0,
    ]
    overall_confidence = sum(mandatory_scores) / len(mandatory_scores)

    extraction = RUTExtraction(
        doc_id=doc_id,
        extraction_engine=ExtractionEngine.PDFPLUMBER,
        extraction_confidence=overall_confidence,
        vat=nit_field,
        name=name_field,
        l10n_co_edi_commercial_name=comercial_field if comercial_field.value else None,
        street=street_field if street_field.value else None,
        city=city_field if city_field.value else None,
        email_dian=email_field if email_field.value else None,
        l10n_co_edi_fiscal_regimen=regimen_field,
        nit_dv_extracted=dv_extracted,
        raw_text=full_text,
    )

    log.info(
        "extraction_done",
        doc_id=doc_id,
        confidence=overall_confidence,
        nit=nit_field.value,
        dv=dv_extracted,
        name=name_field.value,
        regimen=regimen_field.value if regimen_field else None,
    )
    return extraction
