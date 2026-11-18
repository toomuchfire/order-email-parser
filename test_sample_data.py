"""The fictional demo data must load and exercise the business rules as documented."""

from pathlib import Path

from catalog import load_catalog
from rules import load_accounts, load_stock, resolve_line

CATALOG = load_catalog("sample_data/catalog.csv", encoding="utf-8")
STOCK = load_stock("sample_data/stock.csv")


def by_name(fragment):
    return [sku for sku, w in CATALOG.items() if fragment.lower() in w["name"].lower()]


def line(text, skus):
    return {"text": text, "quantity": 1, "unit": "case", "sku": None, "confidence": "low",
            "alternatives": skus}


def test_catalog_and_stock_cover_each_other():
    assert len(CATALOG) == 26
    assert set(CATALOG) == set(STOCK) | {"200105", "200108"}  # the two sold-out wines


def test_every_sample_order_exists_and_names_an_account():
    accounts = load_accounts("sample_data/accounts.json")
    assert len(accounts["accounts"]) == 3
    files = sorted(Path("sample_data/orders").glob("*.txt"))
    assert len(files) == 14


def test_chianti_without_riserva_picks_classico():
    skus = by_name("Chianti Classico")
    result = resolve_line(line("1cs pellarini chianti", skus), CATALOG, STOCK)
    assert CATALOG[result["sku"]]["name"].startswith("Casa Pellarini Chianti Classico 2023")


def test_oldest_in_stock_vintage_is_used():
    result = resolve_line(line("1cs brenvalli primitivo", by_name("Primitivo")), CATALOG, STOCK)
    assert "2023" in CATALOG[result["sku"]]["name"]


def test_sold_out_older_vintage_falls_to_newer():
    result = resolve_line(line("1cs ruscelli montepulciano", by_name("Montepulciano")), CATALOG, STOCK)
    assert "2023" in CATALOG[result["sku"]]["name"]


def test_different_sancerres_stay_ambiguous():
    result = resolve_line(line("1cs faurelle sancerre", by_name("Sancerre")), CATALOG, STOCK)
    assert result["sku"] is None and len(result["alternatives"]) == 3
