"""
Auditoría previa / pre-calificación de cliente a partir de su NIT.

Semáforo:
  VERDE   — señales sólidas de solvencia y cumplimiento
  AMARILLO — datos insuficientes o señales mixtas
  ROJO    — RUT inactivo o señales de riesgo claras

Fuentes consultadas (todas públicas, sin autenticación):
  1. Señales internas del RUT ya extraído
  2. RUES (Confecámaras) — capital suscrito, estado matrícula
  3. DIAN estado RUT     — Activo / Cancelado / Suspendido
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
import structlog

from pipeline.fiscal_intelligence import FiscalProfile

log = structlog.get_logger()

TIMEOUT = 10  # segundos por petición externa
UMBRAL_CAPITAL_COP = 150_000_000  # 150 millones COP


# ── Resultado ────────────────────────────────────────────────────────────────

@dataclass
class PrequalResult:
    nit: str
    semaforo: str                        # "verde" | "amarillo" | "rojo"
    score: int                           # 0–100
    dian_estado: Optional[str] = None    # "Activo" | "Cancelado" | "Suspendido" | None
    rues_capital: Optional[int] = None   # capital suscrito en COP
    rues_estado_matricula: Optional[str] = None
    signals_positivos: list[str] = field(default_factory=list)
    signals_negativos: list[str] = field(default_factory=list)
    fuentes_fallidas: list[str] = field(default_factory=list)
    recomendacion: str = ""

    def as_html(self) -> str:
        color_badge = {
            "verde":    "<span style='color:green'><b>VERDE</b></span>",
            "amarillo": "<span style='color:orange'><b>AMARILLO</b></span>",
            "rojo":     "<span style='color:red'><b>ROJO</b></span>",
        }[self.semaforo]

        pos_html = "".join(f"<li>{s}</li>" for s in self.signals_positivos)
        neg_html = "".join(f"<li>{s}</li>" for s in self.signals_negativos)
        fuentes_count = 2  # DIAN + RUES
        confirmadas = fuentes_count - len(self.fuentes_fallidas)
        if self.fuentes_fallidas:
            base_note = (
                f"Score basado en {confirmadas}/{fuentes_count} fuentes externas "
                f"(no disponibles: {', '.join(self.fuentes_fallidas)}). "
                "El score podría aumentar hasta +40 pts cuando las fuentes estén activas."
            )
            fallas_html = f"<p><small>{base_note}</small></p>"
        else:
            fallas_html = ""
        capital_html = ""
        if self.rues_capital is not None:
            fmt = f"{self.rues_capital:,.0f}".replace(",", ".")
            capital_html = f"<li>Capital suscrito (RUES): <b>${fmt} COP</b></li>"

        dian_html = ""
        if self.dian_estado:
            dian_html = f"<li>Estado RUT (DIAN): <b>{self.dian_estado}</b></li>"

        matricula_html = ""
        if self.rues_estado_matricula:
            matricula_html = f"<li>Estado matrícula (RUES): <b>{self.rues_estado_matricula}</b></li>"

        return (
            f"<h3>Auditoría previa — {color_badge} (score: {self.score}/100)</h3>"
            f"<p><b>Recomendación:</b> {self.recomendacion}</p>"
            f"<ul>{dian_html}{capital_html}{matricula_html}</ul>"
            f"{'<p><b>Señales positivas:</b></p><ul>' + pos_html + '</ul>' if pos_html else ''}"
            f"{'<p><b>Señales de riesgo:</b></p><ul>' + neg_html + '</ul>' if neg_html else ''}"
            f"{fallas_html}"
        )


# ── Fuente 1 : señales internas del RUT ──────────────────────────────────────

# Autorretenedor → DIAN exige ingresos brutos > ~720M COP/año para otorgarlo.
# Implica RUT activo + declaraciones al día (se revoca si el RUT se cancela).
_SCORE_RESP = {
    "15": ("Autorretenedor — ingresos anuales > 720 M COP (certificación DIAN, implica RUT activo)", 40),
    "52": ("Facturador electrónico — al día con obligaciones DIAN",                                  10),
    "42": ("Obligado a llevar contabilidad",                                                          5),
    "10": ("Comercio internacional activo (obligado aduanero)",                                      10),
    "22": ("Importador registrado",                                                                   5),
    "23": ("Exportador registrado",                                                                   5),
    "41": ("Activos en el exterior declarados",                                                       5),
}


def _score_from_rut(profile: FiscalProfile) -> tuple[int, list[str], list[str]]:
    score = 0
    positivos: list[str] = []
    negativos: list[str] = []

    for code in profile.responsibility_codes:
        if code in _SCORE_RESP:
            label, pts = _SCORE_RESP[code]
            score += pts
            positivos.append(label)

    if profile.rut_date:
        # RUT actualizado en los últimos 3 años → señal positiva
        try:
            day, month, year = profile.rut_date.split("-")
            if int(year) >= 2022:
                score += 5
                positivos.append(f"RUT actualizado recientemente ({profile.rut_date})")
        except ValueError:
            pass

    return min(score, 60), positivos, negativos   # cap en 60 — el resto viene de fuentes externas


# ── Fuente 2 : DIAN estado RUT (scraping página pública) ─────────────────────

_DIAN_URL = "https://muisca.dian.gov.co/WebRutMuisca/DefConsultaEstadoRUT.faces"
_DIAN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CO,es;q=0.9",
}
# MUISCA redirige a este host durante ventanas de mantenimiento programado
_DIAN_MAINTENANCE_HOST = "stpaginamantenimiento"


def _check_dian_estado(nit: str) -> Optional[str]:
    """
    Consulta el estado del RUT en la DIAN vía MUISCA.
    Retorna 'Activo', 'Cancelado', 'Suspendido' o None si no disponible.
    """
    try:
        session = requests.Session()
        # allow_redirects=False para detectar mantenimiento antes de seguir
        r1 = session.get(
            _DIAN_URL, headers=_DIAN_HEADERS, timeout=TIMEOUT, allow_redirects=False
        )
        if r1.status_code in (301, 302, 303, 307, 308):
            location = r1.headers.get("Location", "")
            if _DIAN_MAINTENANCE_HOST in location:
                log.warning("dian_en_mantenimiento", nit=nit, location=location)
                return None
            # Seguir la redirección si no es mantenimiento
            r1 = session.get(
                location, headers=_DIAN_HEADERS, timeout=TIMEOUT, allow_redirects=True
            )

        r1.raise_for_status()

        vs_match = re.search(r'id="javax\.faces\.ViewState"[^>]*value="([^"]+)"', r1.text)
        if not vs_match:
            log.warning("dian_viewstate_not_found", nit=nit)
            return None

        payload = {
            "javax.faces.ViewState": vs_match.group(1),
            "vistaConsultaEstadoRUT": "vistaConsultaEstadoRUT",
            "vistaConsultaEstadoRUT:numNit": nit,
            "vistaConsultaEstadoRUT:btnBuscar": "Consultar",
        }
        r2 = session.post(_DIAN_URL, data=payload, headers=_DIAN_HEADERS, timeout=TIMEOUT)
        r2.raise_for_status()

        for estado in ("Activo", "Cancelado", "Suspendido", "Inscrito"):
            if estado.lower() in r2.text.lower():
                log.info("dian_estado_found", nit=nit, estado=estado)
                return estado

        log.warning("dian_estado_not_parsed", nit=nit)
        return None

    except Exception as exc:
        log.warning("dian_check_failed", nit=nit, error=str(exc))
        return None


# ── Fuente 3 : RUES — capital suscrito y estado matrícula ────────────────────

# El endpoint JSON del RUES (POST con XHR → devuelve JSON en el backend JSP legacy).
# La nueva web de RUES (React SPA desde 2024) sirve HTML en todas las rutas públicas,
# pero el backend histórico sigue activo vía POST a /RM/ConsultaRM.
_RUES_URL = "https://www.rues.org.co/RM/ConsultaRM"
_RUES_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "es-CO,es;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://www.rues.org.co",
    "Referer": "https://www.rues.org.co/RM",
}


def _check_rues(nit: str) -> tuple[Optional[int], Optional[str]]:
    """
    Consulta el RUES de Confecámaras.
    Retorna (capital_suscrito_COP, estado_matricula) o (None, None) si no disponible.
    """
    try:
        payload = (
            f"pTipoDoc=NIT&pNIT={nit}&pTipoEmp=ALL"
            "&pRazonSocial=&pDepartamento=0&pMunicipio=0&pEstadoMat=V"
        )
        r = requests.post(
            _RUES_URL, data=payload, headers=_RUES_HEADERS, timeout=TIMEOUT
        )
        r.raise_for_status()

        # Si el Content-Type no es JSON el backend devuelve la SPA HTML → no disponible
        ct = r.headers.get("Content-Type", "")
        if "json" not in ct and "javascript" not in ct:
            log.warning("rues_html_response", nit=nit, content_type=ct)
            return None, None

        data = r.json()

        # Estructura: {"registros": [{"capitalSuscrito": "...", "estadoMatricula": "..."}]}
        registros = data.get("registros") or data.get("data") or []
        if not registros:
            return None, None

        reg = registros[0]
        capital_raw = reg.get("capitalSuscrito") or reg.get("capital_suscrito") or ""
        estado = reg.get("estadoMatricula") or reg.get("estado_matricula")

        capital = None
        if capital_raw:
            digits = re.sub(r"[^\d]", "", str(capital_raw))
            if digits:
                capital = int(digits)

        log.info("rues_found", nit=nit, capital=capital, estado=estado)
        return capital, estado

    except Exception as exc:
        log.warning("rues_check_failed", nit=nit, error=str(exc))
        return None, None


# ── Aplicación de scores por fuente ──────────────────────────────────────────

def _apply_dian_score(
    dian_estado: Optional[str],
    score: int,
    positivos: list[str],
    negativos: list[str],
    fuentes_fallidas: list[str],
) -> int:
    if dian_estado is None:
        fuentes_fallidas.append("DIAN estado RUT")
    elif dian_estado == "Activo":
        score += 20
        positivos.append("RUT activo en la DIAN")
    elif dian_estado in ("Cancelado", "Suspendido"):
        score -= 40
        negativos.append(f"RUT {dian_estado} en la DIAN")
    return score


def _apply_rues_score(
    rues_capital: Optional[int],
    rues_estado: Optional[str],
    score: int,
    positivos: list[str],
    negativos: list[str],
    fuentes_fallidas: list[str],
) -> int:
    if rues_capital is None and rues_estado is None:
        fuentes_fallidas.append("RUES Confecámaras")
        return score

    if rues_capital is not None:
        fmt = f"{rues_capital:,.0f}".replace(",", ".")
        umbral_m = UMBRAL_CAPITAL_COP // 1_000_000
        if rues_capital >= UMBRAL_CAPITAL_COP:
            score += 20
            positivos.append(f"Capital suscrito ${fmt} COP ≥ umbral de {umbral_m} M COP")
        else:
            score -= 5
            negativos.append(f"Capital suscrito ${fmt} COP < umbral de {umbral_m} M COP")

    if rues_estado and rues_estado.lower() not in ("activa", "activo", "vigente"):
        score -= 10
        negativos.append(f"Matrícula mercantil: {rues_estado}")

    return score


def _determine_semaforo(
    score: int,
    negativos: list[str],
    fuentes_fallidas: list[str],
) -> tuple[str, str]:
    """
    ROJO solo por señal negativa confirmada — nunca por ausencia de datos.
    Si las fuentes fallan y el score potencial supera el umbral, retorna AMARILLO provisional.
    """
    rut_inactivo = any("Cancelado" in n or "Suspendido" in n for n in negativos)
    if rut_inactivo:
        return "rojo", "RUT inactivo — no proceder sin verificación manual urgente."

    if score >= 60:
        return "verde", "Perfil sólido. Proceder a negociación sujeto a aprobación de Hector."

    if score >= 35:
        return "amarillo", "Perfil aceptable pero con datos incompletos. Solicitar estados financieros antes de negociar."

    potential_bonus = (20 if "DIAN estado RUT" in fuentes_fallidas else 0) + \
                      (20 if "RUES Confecámaras" in fuentes_fallidas else 0)
    if fuentes_fallidas and (score + potential_bonus) >= 35:
        recomendacion = (
            f"Score provisional ({score}/100) — fuentes externas no disponibles "
            f"({', '.join(fuentes_fallidas)}). "
            f"Score potencial hasta {score + potential_bonus}/100 cuando las fuentes estén activas. "
            "Reintentar antes de tomar una decisión."
        )
        return "amarillo", recomendacion

    return "rojo", "Señales insuficientes o negativas. No proceder sin investigación adicional."


# ── Orchestrador ─────────────────────────────────────────────────────────────

def run_prequalification(nit: str, profile: FiscalProfile) -> PrequalResult:
    """
    Ejecuta la auditoría previa completa.
    Siempre retorna un resultado, incluso si las fuentes externas fallan.
    """
    log.info("prequalification_start", nit=nit)
    t0 = time.monotonic()

    score, positivos, negativos = _score_from_rut(profile)
    fuentes_fallidas: list[str] = []

    dian_estado = _check_dian_estado(nit)
    score = _apply_dian_score(dian_estado, score, positivos, negativos, fuentes_fallidas)

    rues_capital, rues_estado = _check_rues(nit)
    score = _apply_rues_score(rues_capital, rues_estado, score, positivos, negativos, fuentes_fallidas)

    score = max(0, min(100, score))
    semaforo, recomendacion = _determine_semaforo(score, negativos, fuentes_fallidas)

    duration = round(time.monotonic() - t0, 2)
    log.info(
        "prequalification_done",
        nit=nit, semaforo=semaforo, score=score, duration_s=duration,
        fuentes_fallidas=fuentes_fallidas,
    )

    return PrequalResult(
        nit=nit,
        semaforo=semaforo,
        score=score,
        dian_estado=dian_estado,
        rues_capital=rues_capital,
        rues_estado_matricula=rues_estado,
        signals_positivos=positivos,
        signals_negativos=negativos,
        fuentes_fallidas=fuentes_fallidas,
        recomendacion=recomendacion,
    )
