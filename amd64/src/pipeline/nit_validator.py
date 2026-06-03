"""
Validation du NIT colombien avec calcul du dígito de verificación (DV).
Algorithme officiel DIAN — poids [71,67,...,3] sur 15 chiffres avec padding gauche.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Poids DIAN de gauche à droite sur un NIT padé à 15 chiffres
_WEIGHTS = [71, 67, 59, 53, 47, 43, 41, 37, 29, 23, 19, 17, 13, 7, 3]


@dataclass(frozen=True)
class NITResult:
    raw_input: str
    nit: str           # chiffres uniquement, sans DV
    dv_extracted: str | None
    dv_expected: int
    is_valid: bool
    error: str | None = None


def calculate_dv(nit_digits: str) -> int:
    """Calcule le DV d'un NIT à partir de ses chiffres (sans DV)."""
    padded = nit_digits.zfill(15)
    total = sum(int(d) * w for d, w in zip(padded, _WEIGHTS))
    x = total % 11
    return 0 if x == 0 else (1 if x == 1 else 11 - x)


def validate_nit(raw: str) -> NITResult:
    """
    Valide un NIT colombien extrait d'un document.
    Accepte les formats : "890123456-1", "890.123.456-1", "8901234561" (DV collé).
    Retourne NITResult.is_valid=False si le DV ne correspond pas ou si le format est invalide.
    """
    cleaned = re.sub(r"[\s\.]", "", raw.strip())

    # Format avec DV explicite séparé par tiret : "890123456-1"
    m = re.fullmatch(r"(\d{6,15})-(\d)", cleaned)
    if m:
        nit_digits, dv_str = m.group(1), m.group(2)
        dv_expected = calculate_dv(nit_digits)
        is_valid = int(dv_str) == dv_expected
        return NITResult(
            raw_input=raw,
            nit=nit_digits,
            dv_extracted=dv_str,
            dv_expected=dv_expected,
            is_valid=is_valid,
            error=None if is_valid else f"DV extrait={dv_str}, DV attendu={dv_expected}",
        )

    # Format sans séparateur — on tente DV = dernier chiffre
    m2 = re.fullmatch(r"(\d{7,16})", cleaned)
    if m2:
        all_digits = m2.group(1)
        nit_digits, dv_str = all_digits[:-1], all_digits[-1]
        dv_expected = calculate_dv(nit_digits)
        is_valid = int(dv_str) == dv_expected
        return NITResult(
            raw_input=raw,
            nit=nit_digits,
            dv_extracted=dv_str,
            dv_expected=dv_expected,
            is_valid=is_valid,
            error=None if is_valid else f"DV extrait={dv_str}, DV attendu={dv_expected}",
        )

    return NITResult(
        raw_input=raw,
        nit="",
        dv_extracted=None,
        dv_expected=-1,
        is_valid=False,
        error=f"Format NIT non reconnu : '{raw}'",
    )
