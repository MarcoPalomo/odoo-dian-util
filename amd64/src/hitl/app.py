"""
Interface HITL — FastAPI + HTMX pour révision manuelle des documents à confiance faible.
Pas d'authentification : réseau interne uniquement.
"""
from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.audit_log import AuditLog
from pipeline.gates import fields_gate, nit_gate
from pipeline.gates.nit_gate import NITValidationError
from pipeline.models import (
    AuditEntry,
    DocumentSource,
    ExtractionEngine,
    FieldExtraction,
    OdooAction,
    RUTExtraction,
)
from pipeline.fiscal_intelligence import extract_fiscal_profile
from pipeline.odoo_client import OdooClient
from pipeline.prequalification import run_prequalification
from pipeline.queue_client import QueueClient
from pipeline.storage_client import StorageClient

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.queue = QueueClient()
    app.state.storage = StorageClient()
    app.state.audit = AuditLog()
    app.state.odoo = OdooClient()
    yield
    app.state.queue.close()
    app.state.audit.close()


app = FastAPI(title="Pipeline RUT — Revisión Manual", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def queue_list(request: Request):
    messages = await run_in_threadpool(request.app.state.queue.read_hitl)
    documentos = []
    for msg_id, fields in messages:
        documentos.append({
            "msg_id": msg_id,
            "doc_id": fields.get("doc_id", ""),
            "source": fields.get("source", ""),
            "hitl_reason": fields.get("hitl_reason", ""),
            "submitted_at": fields.get("submitted_at", ""),
        })
    pending_count = len(documentos)
    return templates.TemplateResponse(
        "queue.html",
        {"request": request, "documentos": documentos, "pending_count": pending_count},
    )


@app.get("/documento/{doc_id}", response_class=HTMLResponse)
async def documento_form(request: Request, doc_id: str):
    result = await run_in_threadpool(request.app.state.queue.find_hitl_message, doc_id)
    if result is None:
        return HTMLResponse("<p>Documento no encontrado.</p>", status_code=404)

    msg_id, fields = result
    extraction = RUTExtraction.model_validate_json(fields.get("extraction_json", "{}"))
    s3_path = fields.get("s3_path", "")
    pdf_url = await run_in_threadpool(
        request.app.state.storage.get_url, s3_path, 3600
    )
    pending_count = await run_in_threadpool(request.app.state.queue.pending_hitl_count)

    return templates.TemplateResponse(
        "document.html",
        {
            "request": request,
            "doc_id": doc_id,
            "msg_id": msg_id,
            "extraction": extraction,
            "fields": fields,
            "pdf_url": pdf_url,
            "pending_count": pending_count,
        },
    )


@app.post("/documento/{doc_id}/validar", response_class=HTMLResponse)
async def validar(
    request: Request,
    doc_id: str,
    vat: str = Form(...),
    name: str = Form(...),
    nit_dv: str = Form(...),
    regimen: Optional[str] = Form(None),
    nombre_comercial: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    street: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    operador: str = Form(...),
):
    result = await run_in_threadpool(request.app.state.queue.find_hitl_message, doc_id)
    if result is None:
        return HTMLResponse('<div class="alert alert-danger">Documento no encontrado.</div>')

    msg_id, fields = result
    s3_path = fields.get("s3_path", "")
    source_str = fields.get("source", DocumentSource.UPLOAD.value)
    is_cliente = fields.get("is_cliente", "true") == "true"

    # Reconstruire extraction depuis les champs du formulaire
    extraction = RUTExtraction(
        doc_id=doc_id,
        extraction_engine=ExtractionEngine.MANUAL,
        extraction_confidence=1.0,
        vat=FieldExtraction(value=vat.strip(), confidence=1.0),
        name=FieldExtraction(value=name.strip(), confidence=1.0),
        nit_dv_extracted=nit_dv.strip(),
        l10n_co_edi_fiscal_regimen=FieldExtraction(value=regimen, confidence=1.0) if regimen else None,
        l10n_co_edi_commercial_name=FieldExtraction(value=nombre_comercial, confidence=1.0) if nombre_comercial else None,
        email_dian=FieldExtraction(value=email, confidence=1.0) if email else None,
        street=FieldExtraction(value=street, confidence=1.0) if street else None,
        city=FieldExtraction(value=city, confidence=1.0) if city else None,
    )

    try:
        extraction = await run_in_threadpool(nit_gate.run, extraction)
    except NITValidationError as exc:
        return HTMLResponse(
            f'<div id="resultado" class="alert alert-danger">NIT inválido: {exc}</div>'
        )

    try:
        validated = await run_in_threadpool(fields_gate.run, extraction)
    except Exception as exc:
        return HTMLResponse(
            f'<div id="resultado" class="alert alert-danger">Campos inválidos: {exc}</div>'
        )

    odoo: OdooClient = request.app.state.odoo
    audit: AuditLog = request.app.state.audit

    try:
        partner_id, action = await run_in_threadpool(
            odoo.upsert_partner, validated, doc_id, s3_path, is_cliente
        )
        profile = extract_fiscal_profile("")
        note_html = profile.as_html(
            nit=validated.vat,
            dv=nit_dv.strip(),
            source=source_str,
            doc_id=doc_id,
        )
        await run_in_threadpool(odoo.post_import_note, partner_id, note_html)

        prequal = await run_in_threadpool(run_prequalification, validated.vat, profile)
        await run_in_threadpool(
            odoo.create_prequalification_lead,
            partner_id=partner_id,
            partner_name=validated.name,
            prequal_html=prequal.as_html(),
            semaforo=prequal.semaforo,
        )
    except Exception as exc:
        return HTMLResponse(
            f'<div id="resultado" class="alert alert-danger">Error Odoo: {exc}</div>'
        )

    try:
        source = DocumentSource(source_str)
    except ValueError:
        source = DocumentSource.UPLOAD

    await run_in_threadpool(
        audit.write,
        AuditEntry(
            doc_id=doc_id,
            source=source,
            raw_s3_path=s3_path,
            extraction_engine=ExtractionEngine.MANUAL.value,
            extraction_confidence=1.0,
            nit_extracted=validated.vat,
            nit_valid=True,
            needs_hitl=True,
            hitl_operator=operador,
            odoo_partner_id=partner_id,
            odoo_action=action,
        ),
    )

    await run_in_threadpool(
        request.app.state.queue.ack,
        QueueClient.STREAM_HITL,
        QueueClient.GROUP_HITL,
        msg_id,
    )

    return HTMLResponse(
        f'<div id="resultado" class="alert alert-success">'
        f'&#10003; Validado — partner_id {partner_id}'
        f"</div>"
    )


@app.post("/documento/{doc_id}/rechazar", response_class=HTMLResponse)
async def rechazar(
    request: Request,
    doc_id: str,
    motivo: str = Form(...),
    operador: str = Form(...),
):
    result = await run_in_threadpool(request.app.state.queue.find_hitl_message, doc_id)
    if result is None:
        return HTMLResponse('<div class="alert alert-danger">Documento no encontrado.</div>')

    msg_id, fields = result
    s3_path = fields.get("s3_path", "")
    source_str = fields.get("source", DocumentSource.UPLOAD.value)

    await run_in_threadpool(
        request.app.state.queue.publish_failed,
        doc_id, s3_path, source_str, "rechazado_hitl", motivo,
    )

    try:
        source = DocumentSource(source_str)
    except ValueError:
        source = DocumentSource.UPLOAD

    await run_in_threadpool(
        request.app.state.audit.write,
        AuditEntry(
            doc_id=doc_id,
            source=source,
            raw_s3_path=s3_path,
            extraction_engine=ExtractionEngine.MANUAL.value,
            extraction_confidence=1.0,
            needs_hitl=True,
            hitl_operator=operador,
            odoo_action=OdooAction.FAILED,
            error_message=motivo,
        ),
    )

    await run_in_threadpool(
        request.app.state.queue.ack,
        QueueClient.STREAM_HITL,
        QueueClient.GROUP_HITL,
        msg_id,
    )

    return HTMLResponse(
        '<div id="resultado" class="alert alert-warning">&#10007; Documento rechazado.</div>'
    )
