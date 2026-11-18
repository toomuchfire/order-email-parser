from decimal import Decimal

import pytest

from rules import (account_short, apply_line_rules, canonical_account, load_accounts, load_stock,
                   resolve_line, split_inquiries, subject_line)
from validators import has_stray_number, validate_line


ACCOUNTS = load_accounts("sample_data/accounts.json")


def wine(name, price="200"):
    return {"name": name, "brand": "", "price": Decimal(price), "pack_size": 12}


CATALOG = {
    "1": wine('Casa Pellarini Chianti Classico Riserva "Vigna Alta" 2022 (750ml/12)'),
    "2": wine('Casa Pellarini Chianti Classico 2024 (750ml/12)'),
    "3": wine("Cantina Brenvalli Primitivo di Puglia 2024 (750ml/12)"),
    "4": wine("Cantina Brenvalli Primitivo di Puglia 2023 (750ml/12)"),
    "5": wine("Ruscelli Montepulciano d'Abruzzo 2023 (750ml/12)"),
    "6": wine("Ruscelli Montepulciano d'Abruzzo 2022 (750ml/12)"),
    "7": wine("Faurelle Sancerre Les Pierres 2025 (750ml/12)"),
    "8": wine("Faurelle Sancerre Cuvee Silex 2025 (750ml/12)"),
}


def line(text, sku=None, alternatives=(), **extra):
    return {"text": text, "quantity": 1, "unit": "case", "sku": sku,
            "confidence": "low", "alternatives": list(alternatives), **extra}


# ----- accounts -----

@pytest.mark.parametrize("raw, expected", [
    ("NB Specialty - Wine", "Harbor & Vine North Beach (NB)"),
    ("Harbor & Vine cedar hills", "Harbor & Vine Cedar Hills (CH)"),
    ("H&V Marina", "Harbor & Vine Marina (MR)"),
    ("North Beach", "Harbor & Vine North Beach (NB)"),
    ("Acme Wines", None),
    (None, None),
])
def test_canonical_account(raw, expected):
    assert canonical_account(raw, accounts=ACCOUNTS) == expected


def test_account_falls_back_to_next_text():
    assert canonical_account("Wine Buyer", "CH order 3/12", accounts=ACCOUNTS) == "Harbor & Vine Cedar Hills (CH)"


def test_two_accounts_in_one_text_is_not_guessed():
    assert canonical_account("NB and CH order", accounts=ACCOUNTS) is None


def test_account_short():
    assert account_short("Harbor & Vine Marina (MR)", ACCOUNTS) == "MR"
    assert account_short("Unknown", ACCOUNTS) == "Unknown"


def test_load_accounts_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_accounts(tmp_path / "nope.json")


def test_subject_line():
    assert subject_line("From: a\nSubject: CB Wine Order 10/22\n\nHi") == "CB Wine Order 10/22"
    assert subject_line("no subject here") == ""


# ----- Riserva -----

def test_no_riserva_means_classico():
    result = resolve_line(line("1cs pellarini Chianti", None, ["1", "2"]), CATALOG)
    assert result["sku"] == "2" and result["alternatives"] == [] and result["confidence"] == "high"


def test_riserva_named_means_riserva():
    result = resolve_line(line("1 Pellarini Chianti Classico Riserva", "2", ["1"]), CATALOG)
    assert result["sku"] == "1"


# ----- vintage -----

def test_vintage_without_stock_list_is_flagged():
    result = resolve_line(line("1 Brenvalli Primitivo", "3", ["4"]), CATALOG, stock=None)
    assert result["sku"] is None and set(result["alternatives"]) == {"3", "4"}
    assert "stock.csv" in result["note"]


def test_oldest_vintage_in_stock_wins():
    result = resolve_line(line("1cs brenvalli primitivo", "3", ["4"]), CATALOG, stock={"3", "4"})
    assert result["sku"] == "4" and "2023" in result["note"]


def test_older_vintage_out_of_stock_falls_to_newer():
    result = resolve_line(line("1cs brenvalli primitivo", "3", ["4"]), CATALOG, stock={"3"})
    assert result["sku"] == "3"


def test_all_vintages_out_of_stock_is_flagged():
    result = resolve_line(line("1cs brenvalli primitivo", "3", ["4"]), CATALOG, stock=set())
    assert result["sku"] is None and "out of stock" in result["note"]


def test_customer_named_vintage_wins():
    result = resolve_line(line("2cs Ruscelli Montepulciano 2023", "5", ["6"]), CATALOG, stock={"5", "6"})
    assert result["sku"] == "5" and "note" not in result


def test_different_wines_are_left_ambiguous():
    result = resolve_line(line("faurelle Sancerre", "7", ["8"]), CATALOG, stock={"7", "8"})
    assert result["sku"] == "7" and result["alternatives"] == ["7", "8"]


def test_single_match_is_untouched():
    original = line("1 Faurelle Sancerre Silex", "8", [], confidence="high")
    assert resolve_line(original, CATALOG) == original


def test_flagged_vintage_line_reports_the_reason():
    flagged = resolve_line(line("1 Brenvalli Primitivo", "3", ["4"]), CATALOG)
    problems = validate_line(flagged, CATALOG)
    assert problems and "stock.csv" in problems[0]


def test_apply_line_rules_covers_every_line():
    order = {"account": "x", "lines": [line("pellarini Chianti", None, ["1", "2"])]}
    assert apply_line_rules(order, CATALOG)["lines"][0]["sku"] == "2"


# ----- inquiries -----

def test_inquiries_are_split_out():
    order = {"lines": [line("1cs faurelle menetou blanc", kind="order"), line("TL Chablis", kind="inquiry")]}
    kept, inquiries = split_inquiries(order)
    assert [l["text"] for l in kept["lines"]] == ["1cs faurelle menetou blanc"]
    assert [l["text"] for l in inquiries] == ["TL Chablis"]


def test_returns_are_set_aside_like_inquiries():
    order = {"lines": [line("1cs Faurelle Sancerre (didn't receive)", kind="return"), line("1cs willow ridge", kind="order")]}
    kept, set_aside = split_inquiries(order)
    assert [l["text"] for l in kept["lines"]] == ["1cs willow ridge"]
    assert set_aside[0]["kind"] == "return"


def test_lines_without_a_kind_count_as_orders():
    kept, inquiries = split_inquiries({"lines": [line("1 Sancerre")]})
    assert len(kept["lines"]) == 1 and inquiries == []


# ----- stock file -----

def test_load_stock_missing_file_is_none(tmp_path):
    assert load_stock(tmp_path / "nope.csv") is None


def test_load_stock_reads_yes_no_and_numbers(tmp_path):
    path = tmp_path / "stock.csv"
    path.write_text("Item #,In Stock\n3,yes\n4,no\n5,12\n6,0\n7,TRUE\n")
    assert load_stock(path) == {"3", "5", "7"}


def test_load_stock_needs_the_right_columns(tmp_path):
    path = tmp_path / "stock.csv"
    path.write_text("wine,color\nx,red\n")
    with pytest.raises(ValueError):
        load_stock(path)


# ----- stray numbers -----

@pytest.mark.parametrize("text, expected", [
    ("1 case 1 Vireaux Chablis", True),
    ("1cs Willow Ridge SB", False),
    ("2cs Ruscelli Montepulciano D’abruzzo", False),
    ("1 Pinot Noir 2023", False),
    ("1 Chablis 750ml", False),
])
def test_has_stray_number(text, expected):
    assert has_stray_number(text) is expected
