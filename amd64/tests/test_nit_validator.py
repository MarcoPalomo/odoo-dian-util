"""Tests du validateur NIT colombien (algo DV DIAN)."""
import pytest
from pipeline.nit_validator import calculate_dv, validate_nit


# Cas connus — NIT réels DIAN avec DV vérifié
VALID_CASES = [
    ("800197268-4", "800197268", "4"),    # Bancolombia
    ("860007335-4", "860007335", "4"),    # ETB
    ("900775123-8", "900775123", "8"),
    ("890903938-8", "890903938", "8"),    # EPM
    ("830115297-6", "830115297", "6"),
]

INVALID_DV_CASES = [
    "800197268-0",  # DV incorrect (devrait être 4)
    "860007335-9",
    "890903938-1",
]

FORMAT_ERROR_CASES = [
    "ABC123",
    "123",        # trop court
    "",
    "NIT: SIN",
]


@pytest.mark.parametrize("raw,expected_nit,expected_dv", VALID_CASES)
def test_valid_nit(raw, expected_nit, expected_dv):
    result = validate_nit(raw)
    assert result.is_valid, f"Attendu valide pour {raw}: {result.error}"
    assert result.nit == expected_nit
    assert result.dv_extracted == expected_dv


@pytest.mark.parametrize("raw", INVALID_DV_CASES)
def test_invalid_dv(raw):
    result = validate_nit(raw)
    assert not result.is_valid


@pytest.mark.parametrize("raw", FORMAT_ERROR_CASES)
def test_format_errors(raw):
    result = validate_nit(raw)
    assert not result.is_valid
    assert result.error is not None


def test_dotted_format():
    # "800.197.268-4" — format avec points
    result = validate_nit("800.197.268-4")
    assert result.is_valid
    assert result.nit == "800197268"


def test_no_separator_format():
    # DV collé : "8001972684"
    result = validate_nit("8001972684")
    assert result.is_valid
    assert result.nit == "800197268"


def test_calculate_dv_direct():
    assert calculate_dv("800197268") == 4
    assert calculate_dv("860007335") == 4
    assert calculate_dv("890903938") == 8
