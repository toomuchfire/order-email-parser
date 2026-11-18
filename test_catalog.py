import logging
from decimal import Decimal

import pytest

from catalog import load_catalog, parse_pack_size, parse_price

SAMPLE = """,,,,,,,,,
,,,Some Contact,,,,,,
,,,,,,,,,
Item #,UPC,Brand Name,Item Description,Appellation & Region,Notes,FL Price,Price,Press & Practice
ITALY,,,,,,,,
100001,111,Brand A,Brand A Red 2020 (750ml/12),Piedmont,,$90 ,"$1,200 ",WA: 95
100002,222,Brand B,Brand B White 2021 (750ml/6),Loire,,,$96 ,
100002,333,Brand C,Brand C Dupe 2022 (750ml/12),Loire,,,$50 ,
100003,444,Brand D,Brand D No Price 2022 (750ml/12),Loire,,,,
100004,555,Brand E,Brand E Bad Price 2022 (750ml/12),Loire,,,call us,
"""


@pytest.fixture
def csv_path(tmp_path):
    p = tmp_path / "wines.csv"
    p.write_text(SAMPLE, encoding="cp1252")
    return p


def test_loads_valid_rows_and_skips_noise(csv_path):
    cat = load_catalog(csv_path)
    assert set(cat) == {"100001", "100002"}
    assert cat["100001"]["price"] == Decimal("1200")
    assert cat["100001"]["pack_size"] == 12
    assert cat["100002"]["pack_size"] == 6


def test_duplicate_sku_keeps_first_and_logs(csv_path, caplog):
    with caplog.at_level(logging.WARNING):
        cat = load_catalog(csv_path)
    assert cat["100002"]["brand"] == "Brand B"
    assert "duplicate SKU 100002" in caplog.text


def test_missing_or_invalid_price_is_skipped(csv_path, caplog):
    with caplog.at_level(logging.WARNING):
        cat = load_catalog(csv_path)
    assert "100003" not in cat and "100004" not in cat
    assert "SKU 100003 skipped" in caplog.text


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        load_catalog(tmp_path / "nope.csv")


def test_missing_header_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="Item #"):
        load_catalog(p)


def test_helpers():
    assert parse_price("$960 ") == Decimal("960")
    assert parse_price("") is None
    assert parse_pack_size("Foo (750ml/12)") == 12
    assert parse_pack_size("Foo") is None
