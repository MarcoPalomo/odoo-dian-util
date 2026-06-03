"""
Extracción del perfil de inteligencia fiscal desde el texto bruto de un RUT DIAN.
Sin APIs externas — todo proviene del documento.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Códigos de responsabilidad DIAN
_RESP_LABELS: dict[str, str] = {
    "05": "Impuesto renta — régimen ordinario",
    "06": "Impuesto renta — régimen especial",
    "07": "Retención en la fuente — renta",
    "09": "Retención en la fuente — IVA",
    "10": "Obligado aduanero",
    "14": "Informante de exógena",
    "15": "Autorretenedor",
    "16": "Obligación de facturar",
    "19": "Productor de bienes/servicios exentos",
    "22": "Importador",
    "23": "Exportador",
    "32": "IVA cuatrimestral",
    "33": "IVA anual",
    "41": "Declaración anual activos en el exterior",
    "42": "Obligado a llevar contabilidad",
    "47": "Régimen tributario especial",
    "48": "IVA",
    "49": "No responsable de IVA",
    "50": "INC (bebidas/cigarrillos)",
    "51": "INC (comidas rápidas)",
    "52": "Facturador electrónico",
    "53": "Régimen simple de tributación",
    "55": "Informante de beneficiarios finales",
}

# Señales de envergadura — presencia de estos códigos indica empresa de peso
_SIGNALS = {
    "15": "Autorretenedor (empresa de ingresos significativos — calidad otorgada por la DIAN)",
    "41": "Activos en el exterior (patrimonio internacional declarado)",
    "10": "Obligado aduanero (comercio internacional activo)",
    "22": "Importador",
    "23": "Exportador",
}

# Códigos CIIU más frecuentes en la industria colombiana
_CIIU_SECTORS: dict[str, str] = {
    "0111": "Agricultura — cereales y leguminosas",
    "0121": "Agricultura — café",
    "1011": "Procesamiento de carnes",
    "1020": "Procesamiento de pescado y mariscos",
    "1030": "Procesamiento de frutas y verduras",
    "1040": "Aceites y grasas de origen vegetal y animal",
    "1050": "Elaboración de productos lácteos",
    "1061": "Molinería — cereales",
    "1081": "Elaboración de azúcar",
    "1082": "Cacao, chocolate y confitería",
    "1089": "Elaboración de otros productos alimenticios",
    "1511": "Curtido y preparado de cueros",
    "1610": "Aserrado y acepillado de madera",
    "1701": "Fabricación de pulpa, papel y cartón",
    "2011": "Fabricación de sustancias químicas básicas",
    "2100": "Fabricación de productos farmacéuticos",
    "2310": "Fabricación de vidrio",
    "2391": "Fabricación de productos refractarios",
    "2410": "Industria siderúrgica básica",
    "2511": "Fabricación de productos metálicos estructurales",
    "2592": "Tratamiento y revestimiento de metales",
    "2610": "Fabricación de componentes electrónicos",
    "2740": "Fabricación de equipos de iluminación",
    "2811": "Fabricación de motores y turbinas",
    "2910": "Fabricación de vehículos automotores",
    "3250": "Fabricación de instrumentos médicos",
    "3511": "Generación de energía eléctrica",
    "3530": "Suministro de vapor y aire acondicionado",
    "4111": "Construcción de edificios residenciales",
    "4112": "Construcción de edificios no residenciales",
    "4210": "Construcción de carreteras y vías",
    "4511": "Comercio de vehículos automotores",
    "4631": "Comercio al por mayor de productos alimenticios",
    "4632": "Comercio al por mayor de bebidas y tabaco",
    "4641": "Comercio al por mayor de textiles",
    "4649": "Comercio al por mayor de otros productos",
    "4711": "Comercio al por menor de alimentos",
    "4721": "Comercio al por menor de carnes",
    "4912": "Transporte férreo",
    "4921": "Transporte urbano de pasajeros",
    "4930": "Transporte por tuberías",
    "5111": "Transporte aéreo nacional",
    "5210": "Almacenamiento y depósito",
    "5510": "Alojamiento en hoteles",
    "5611": "Expendio de comidas preparadas",
    "6110": "Telecomunicaciones alámbricas",
    "6120": "Telecomunicaciones inalámbricas",
    "6201": "Desarrollo de sistemas informáticos",
    "6209": "Otras actividades de tecnología informática",
    "6411": "Banco central",
    "6412": "Bancos comerciales",
    "6491": "Leasing financiero",
    "6511": "Seguros de vida",
    "6512": "Seguros generales",
    "6614": "Corretaje de valores",
    "6810": "Actividades inmobiliarias — promotores",
    "6820": "Arrendamiento de bienes inmuebles",
    "7010": "Administración empresarial — holding",
    "7020": "Consultorías de gestión empresarial",
    "7110": "Actividades de ingeniería",
    "7310": "Publicidad",
    "7490": "Otras actividades profesionales",
    "7710": "Alquiler de vehículos",
    "8010": "Actividades de seguridad privada",
    "8121": "Limpieza general de edificios",
    "8292": "Actividades de envase y empaque",
    "8411": "Administración pública",
    "8512": "Educación básica primaria",
    "8610": "Actividades de hospitales",
    "8621": "Medicina general",
    "8690": "Otras actividades de atención de la salud",
    "9001": "Artes escénicas",
    "9200": "Juegos de azar",
    "9311": "Gestión de instalaciones deportivas",
    "9601": "Lavado y limpieza de prendas",
}

_RE_CIIU_ROW = re.compile(
    r"46\.\s*C[óo]digo[^\n]*\n\s*(\d(?:\s+\d){3})",  # exactamente 4 dígitos
    re.IGNORECASE,
)
_RE_RESP_BLOCK = re.compile(
    r"Responsabilidades.*(?=\n\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)
# El guion debe ir seguido de letra para evitar falsos positivos en fechas (06-01-2026)
_RE_RESP_CODE_LINE = re.compile(r"\b(\d{2})\s*[-–]\s*[A-Za-zÁÉÍÓÚÑáéíóúñ]")

_RE_RUT_DATE = re.compile(
    r"Fecha\s+generaci[óo]n\s+documento\s+PDF[:\s]+(\d{2}-\d{2}-\d{4})",
    re.IGNORECASE,
)


@dataclass
class FiscalProfile:
    ciiu_code: str | None = None
    ciiu_sector: str | None = None
    responsibility_codes: list[str] = field(default_factory=list)
    responsibility_labels: list[str] = field(default_factory=list)
    notable_signals: list[str] = field(default_factory=list)
    rut_date: str | None = None

    def as_html(self, nit: str, dv: str, source: str, doc_id: str) -> str:
        codes_html = "".join(
            f"<li><b>{c}</b> — {l}</li>"
            for c, l in zip(self.responsibility_codes, self.responsibility_labels)
        )
        signals_html = ""
        if self.notable_signals:
            items = "".join(f"<li>{s}</li>" for s in self.notable_signals)
            signals_html = f"<p><b>Señales de envergadura:</b></p><ul>{items}</ul>"

        ciiu_html = ""
        if self.ciiu_code:
            sector = f" — {self.ciiu_sector}" if self.ciiu_sector else ""
            ciiu_html = f"<p><b>Actividad principal (CIIU):</b> {self.ciiu_code}{sector}</p>"

        return (
            f"<p><b>Importación RUT automática</b> — fuente: {source}"
            f"{' | ' + self.rut_date if self.rut_date else ''}</p>"
            f"<p>NIT: <b>{nit}-{dv}</b> — DV verificado</p>"
            f"{ciiu_html}"
            f"<p><b>Perfil fiscal ({len(self.responsibility_codes)} responsabilidades):</b></p>"
            f"<ul>{codes_html}</ul>"
            f"{signals_html}"
            f"<p><small>doc_id={doc_id}</small></p>"
        )


def extract_fiscal_profile(raw_text: str) -> FiscalProfile:
    profile = FiscalProfile()

    m = _RE_CIIU_ROW.search(raw_text)
    if m:
        profile.ciiu_code = re.sub(r"\s+", "", m.group(1))
        profile.ciiu_sector = _CIIU_SECTORS.get(profile.ciiu_code)

    found_codes = set(_RE_RESP_CODE_LINE.findall(raw_text))
    resp_codes = sorted(c for c in found_codes if c in _RESP_LABELS)
    profile.responsibility_codes = resp_codes
    profile.responsibility_labels = [_RESP_LABELS[c] for c in resp_codes]
    profile.notable_signals = [_SIGNALS[c] for c in resp_codes if c in _SIGNALS]

    m_date = _RE_RUT_DATE.search(raw_text)
    if m_date:
        profile.rut_date = m_date.group(1)

    return profile
