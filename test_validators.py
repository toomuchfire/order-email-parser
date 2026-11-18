import pytest
from decimal import Decimal

from validators import (check_quantity, line_amounts, looks_like_match, unit_price,
                        validate_line, validate_order)

CATALOG = {
    "200302": {"name": "Willow Ridge Sauvignon Blanc 2025 (750ml/12)", "price": Decimal("112"), "pack_size": 12},
    "200102": {"name": 'Casa Pellarini Chianti Classico Riserva "Vigna Alta" 2022 (750ml/12)', "price": Decimal("204"), "pack_size": 12},
    "200101": {"name": 'Casa Pellarini Chianti Classico 2024 (750ml/12)', "price": Decimal("168"), "pack_size": 12},
    "200140": {"name": "Poderi Valmera Nebbiolo d’Alba 2024 (750ml/12)", "price": Decimal("240"), "pack_size": 12},
    "100001": {"name": "Odd Pack Wine (1500ml)", "price": Decimal("90"), "pack_size": None},
}


def line(**kw):
    base = {"text": "1 Willow Ridge Sauv Blanc", "quantity": 1, "unit": "case",
            "sku": "200302", "confidence": "high", "alternatives": []}
    base.update(kw)
    return base


def order(*lines, account="Harbor & Vine"):
    return {"account": account, "lines": list(lines)}


# --- matching ---------------------------------------------------------------
def test_clean_match_passes():
    assert validate_line(line(), CATALOG) == []


def test_unmatched_line_flagged():
    problems = validate_line(line(sku=None, text="1 Chateau Margaux"), CATALOG)
    assert problems == ["could not match '1 Chateau Margaux' to an approved wine"]


def test_ambiguous_line_lists_candidates():
    problems = validate_line(line(text="1 Pellarini Chianti Classico", sku=None, confidence="low",
                                  alternatives=["200102", "200101"]), CATALOG)
    assert "ambiguous" in problems[0] and "200102" in problems[0] and "200101" in problems[0]


def test_best_guess_with_alternatives_still_flagged():
    problems = validate_line(line(text="1 Pellarini Chianti Classico", sku="200101", confidence="low",
                                  alternatives=["200102", "200101"]), CATALOG)
    assert "ambiguous" in problems[0] and "200102" in problems[0]


def test_invented_sku_flagged():
    assert "not in the approved list" in validate_line(line(sku="999999"), CATALOG)[0]


def test_low_confidence_flagged():
    assert "low-confidence" in validate_line(line(confidence="low"), CATALOG)[0]


def test_match_that_does_not_resemble_the_line_flagged():
    problems = validate_line(line(text="2 Hartwell Pinot Noir", sku="200302"), CATALOG)
    assert "does not look like" in problems[0]


@pytest.mark.parametrize("text,name", [
    ("1 Willow Ridge Sauv Blanc", "Willow Ridge Sauvignon Blanc 2025"),
    ("2 Poderi Valmera Nebbiolo d'Alba", "Poderi Valmera Nebbiolo d’Alba 2024"),
    ("1 Valmera Nebb dalba", "Poderi Valmera Nebbiolo d’Alba 2024"),
])
def test_abbreviations_look_like_a_match(text, name):
    assert looks_like_match(text, name)


# --- quantity and unit --------------------------------------------------------
@pytest.mark.parametrize("qty", [0, -1, 1.5, "abc", None, "", True])
def test_bad_quantities_flagged(qty):
    assert check_quantity(qty) is not None


@pytest.mark.parametrize("qty", [1, "3", 2.0, " 4 "])
def test_good_quantities_pass(qty):
    assert check_quantity(qty) is None


def test_unknown_unit_flagged():
    assert "not case or bottle" in validate_line(line(unit="pallet"), CATALOG)[0]


def test_missing_unit_defaults_to_case():
    assert validate_line(line(unit=None), CATALOG) == []


def test_bottles_of_a_wine_with_no_pack_size_flagged():
    problems = validate_line(line(text="3 btl Odd Pack Wine", sku="100001", unit="bottle", quantity=3), CATALOG)
    assert "pack size unknown" in problems[0]


# --- prices and totals ----------------------------------------------------------
def test_bottle_price_is_case_price_over_pack_size():
    assert unit_price(CATALOG["200102"], "bottle") == Decimal("17.00")
    assert unit_price(CATALOG["200102"], "case") == Decimal("204")


def test_line_amounts_for_cases_and_bottles():
    assert line_amounts(line(quantity=2), CATALOG) == (Decimal("224"), Decimal("2"))
    dollars, cases = line_amounts(line(quantity=6, unit="bottle"), CATALOG)
    assert dollars == Decimal("56") and cases == Decimal("0.5")


# --- whole orders ---------------------------------------------------------------
def test_valid_order_over_dollar_minimum_passes():
    ok, reasons = validate_order(order(line(quantity=3)), CATALOG)  # $336, 3 cases
    assert ok and reasons == []


def test_valid_order_over_case_minimum_passes_even_if_cheap():
    cheap = {"X": {"name": "Cheap Wine", "price": Decimal("40"), "pack_size": 12}}
    ok, _ = validate_order(order(line(text="4 Cheap Wine", sku="X", quantity=4)), cheap)  # $160, 4 cases
    assert ok


def test_below_both_minimums_flagged():
    ok, reasons = validate_order(order(line(quantity=1)), CATALOG)  # $112, 1 case
    assert not ok and "below order minimum" in reasons[0]


def test_bottle_order_counts_as_fraction_of_a_case():
    ok, reasons = validate_order(order(line(quantity=6, unit="bottle")), CATALOG)
    assert not ok and "0.50 cases" in reasons[0]


def test_missing_account_flagged():
    ok, reasons = validate_order(order(line(quantity=3), account=""), CATALOG)
    assert not ok and reasons == ["account not identified"]


def test_empty_order_flagged():
    ok, reasons = validate_order(order(), CATALOG)
    assert not ok and "no order lines found" in reasons


def test_line_problems_carry_line_numbers_and_skip_the_minimum_check():
    ok, reasons = validate_order(order(line(quantity=3), line(quantity=0)), CATALOG)
    assert reasons == ["line 2: quantity 0 must be greater than zero"]
