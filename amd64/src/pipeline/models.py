from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ExtractionEngine(str, Enum):
    PDFPLUMBER = "pdfplumber"
    GOOGLE_DOCAI = "google_docai"
    TESSERACT = "tesseract"
    MANUAL = "manual"


class OdooAction(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


class DocumentSource(str, Enum):
    EMAIL = "email"
    UPLOAD = "upload"
    WHATSAPP = "whatsapp"


class FieldExtraction(BaseModel):
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class RUTExtraction(BaseModel):
    doc_id: str
    extraction_engine: ExtractionEngine
    extraction_confidence: float = Field(ge=0.0, le=1.0)

    # Champs Odoo vérifiés sur l'instance industriaspico
    vat: Optional[FieldExtraction] = None          # NIT sans DV
    name: Optional[FieldExtraction] = None         # Razón Social
    l10n_latam_identification_type_id: int = 4     # NIT en Colombie = 4 (vérifié sur l'instance)
    l10n_co_edi_fiscal_regimen: Optional[FieldExtraction] = None
    l10n_co_edi_commercial_name: Optional[FieldExtraction] = None
    email_dian: Optional[FieldExtraction] = None
    street: Optional[FieldExtraction] = None
    city: Optional[FieldExtraction] = None

    nit_dv_extracted: Optional[str] = None        # DV tel qu'extrait du document
    nit_dv_valid: bool = False
    needs_hitl: bool = False
    raw_text: Optional[str] = None                # texte brut du PDF, pour debug


class ValidatedRUT(BaseModel):
    """Résultat après passage par toutes les gates — prêt pour Odoo."""
    doc_id: str
    vat: str                                       # NIT propre, sans DV
    name: str
    l10n_latam_identification_type_id: int = 31
    l10n_co_edi_fiscal_regimen: Optional[str] = None
    l10n_co_edi_commercial_name: Optional[str] = None
    email_dian: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    extraction_engine: ExtractionEngine
    extraction_confidence: float


class AuditEntry(BaseModel):
    doc_id: str
    source: DocumentSource
    raw_s3_path: Optional[str] = None
    extraction_engine: Optional[str] = None
    extraction_confidence: Optional[float] = None
    nit_extracted: Optional[str] = None
    nit_valid: Optional[bool] = None
    needs_hitl: bool = False
    hitl_operator: Optional[str] = None
    odoo_partner_id: Optional[int] = None
    odoo_action: Optional[OdooAction] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
