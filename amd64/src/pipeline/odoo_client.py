"""
Client Odoo XML-RPC — upsert idempotent sur vat, avec retry et tags CO.
Base cible : industriaspico-industriaspico-main-14967325
"""
from __future__ import annotations

import os
import xmlrpc.client
from typing import Optional

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.models import OdooAction, ValidatedRUT

log = structlog.get_logger()

ODOO_URL = os.getenv("ODOO_URL", "")
ODOO_DB = os.getenv("ODOO_DB", "industriaspico-industriaspico-main-14967325")
ODOO_USER = os.getenv("ODOO_USER", "")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")

# Tags Odoo existants sur l'instance — ne pas en recréer
TAG_CLIENTE = "Cliente"
TAG_PROVEEDOR = "Proveedor"
TAG_B2B = "B2B"
TAG_IMPORT_AUTO = "Import_Auto"

MODEL_LEAD = "crm.lead"


class OdooClient:
    def __init__(
        self,
        url: str = ODOO_URL,
        db: str = ODOO_DB,
        user: str = ODOO_USER,
        password: str = ODOO_PASSWORD,
    ):
        self._url = url
        self._db = db
        self._user = user
        self._password = password
        self._uid: Optional[int] = None
        self._models: Optional[xmlrpc.client.ServerProxy] = None

    def _connect(self) -> None:
        common = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/common")
        self._uid = common.authenticate(self._db, self._user, self._password, {})
        if not self._uid:
            raise ConnectionError(
                f"Authentification Odoo échouée pour user={self._user} db={self._db}"
            )
        self._models = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/object")
        log.info("odoo_connected", uid=self._uid, db=self._db)

    def _ensure_connected(self) -> None:
        if self._uid is None:
            self._connect()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call(self, model: str, method: str, args: list, kwargs: dict = None) -> object:
        self._ensure_connected()
        return self._models.execute_kw(
            self._db, self._uid, self._password,
            model, method, args, kwargs or {},
        )

    def get_or_create_tag(self, name: str) -> int:
        """Retourne l'id du tag, le crée s'il n'existe pas."""
        existing = self._call(
            "res.partner.category", "search_read",
            [[["name", "=", name]]],
            {"fields": ["id"], "limit": 1},
        )
        if existing:
            return existing[0]["id"]
        tag_id = self._call("res.partner.category", "create", [{"name": name}])
        log.info("tag_created", name=name, id=tag_id)
        return tag_id

    def upsert_partner(
        self,
        rut: ValidatedRUT,
        doc_id: str,
        s3_path: str,
        is_cliente: bool = True,
    ) -> tuple[int, OdooAction]:
        """
        Upsert idempotent sur vat.
        Retourne (partner_id, action) où action est 'created' ou 'updated'.
        """
        tag_import_id = self.get_or_create_tag(TAG_IMPORT_AUTO)
        tag_b2b_id = self.get_or_create_tag(TAG_B2B)
        tag_role_id = self.get_or_create_tag(TAG_CLIENTE if is_cliente else TAG_PROVEEDOR)

        vals: dict = {
            "vat": rut.vat,
            "name": rut.name,
            "is_company": True,
            "country_id": 49,       # Colombie — id stable sur l'instance
            "l10n_latam_identification_type_id": rut.l10n_latam_identification_type_id,
            "category_id": [
                (4, tag_import_id),
                (4, tag_b2b_id),
                (4, tag_role_id),
            ],
            "comment": f"[Pipeline] doc_id={doc_id} | s3={s3_path}",
        }

        if rut.l10n_co_edi_fiscal_regimen:
            vals["l10n_co_edi_fiscal_regimen"] = rut.l10n_co_edi_fiscal_regimen
        if rut.l10n_co_edi_commercial_name:
            vals["l10n_co_edi_commercial_name"] = rut.l10n_co_edi_commercial_name
        if rut.email_dian:
            vals["email"] = rut.email_dian
        if rut.street:
            vals["street"] = rut.street
        if rut.city:
            vals["city"] = rut.city

        existing = self._call(
            "res.partner", "search_read",
            [[["vat", "=", rut.vat]]],
            {"fields": ["id", "name", "vat"], "limit": 1},
        )

        if existing:
            partner_id = existing[0]["id"]
            self._call("res.partner", "write", [[partner_id], vals])
            log.info(
                "odoo_partner_updated",
                doc_id=doc_id,
                partner_id=partner_id,
                vat=rut.vat,
            )
            return partner_id, OdooAction.UPDATED
        else:
            partner_id = self._call("res.partner", "create", [vals])
            log.info(
                "odoo_partner_created",
                doc_id=doc_id,
                partner_id=partner_id,
                vat=rut.vat,
                name=rut.name,
            )
            return partner_id, OdooAction.CREATED

    def post_import_note(self, partner_id: int, body_html: str) -> None:
        """Poste une note interne (chatter) sur la fiche contact."""
        self._call(
            "res.partner", "message_post",
            [[partner_id]],
            {"body": body_html, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
        )
        log.info("chatter_note_posted", partner_id=partner_id)

    def create_prequalification_lead(
        self,
        partner_id: int,
        partner_name: str,
        prequal_html: str,
        semaforo: str,
    ) -> int:
        """
        Crea una oportunidad CRM en etapa 'New' con el resultado de la auditoría previa.
        Hector revisará y dará GO/NO-GO.
        """
        # Obtener la etapa "New" del pipeline CRM existente
        stages = self._call(
            "crm.stage", "search_read",
            [[["name", "ilike", "new"]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        stage_id = stages[0]["id"] if stages else False

        etiquetas = {"verde": "GO — auditoría positiva", "amarillo": "REVISAR — datos incompletos", "rojo": "NO-GO — riesgo alto"}
        lead_vals = {
            "name": f"[{semaforo.upper()}] Auditoría previa — {partner_name}",
            "partner_id": partner_id,
            "description": prequal_html,
            "type": "opportunity",
            "tag_ids": [],
        }
        if stage_id:
            lead_vals["stage_id"] = stage_id

        lead_id = self._call(MODEL_LEAD, "create", [lead_vals])
        log.info(
            "crm_lead_created",
            lead_id=lead_id,
            partner_id=partner_id,
            semaforo=semaforo,
        )
        return lead_id

    def update_lead_prequal(
        self,
        lead_id: int,
        partner_name: str,
        prequal_html: str,
        semaforo_prev: str,
        semaforo_new: str,
    ) -> None:
        """Met à jour une lead CRM existante après retry de pré-qualification."""
        if semaforo_new != semaforo_prev:
            new_name = f"[{semaforo_new.upper()}] Auditoría previa — {partner_name}"
            self._call(MODEL_LEAD, "write", [[lead_id], {"name": new_name}])

        note = (
            f"<b>🔄 Auditoría previa actualizada</b> "
            f"(semáforo: {semaforo_prev.upper()} → {semaforo_new.upper()})<br/>"
            f"{prequal_html}"
        )
        self._call(
            MODEL_LEAD, "message_post",
            [[lead_id]],
            {"body": note, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
        )
        log.info("lead_prequal_updated", lead_id=lead_id,
                 semaforo_prev=semaforo_prev, semaforo_new=semaforo_new)

    def get_country_id_co(self) -> int:
        """Retourne l'id Odoo de la Colombie (vérification)."""
        result = self._call(
            "res.country", "search_read",
            [[["code", "=", "CO"]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        return result[0]["id"] if result else 49
