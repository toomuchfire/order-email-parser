from datetime import date
from decimal import Decimal

from rules import load_accounts
from drafts import build_draft, format_line, format_money, when_phrase, write_drafts

ACCOUNTS = load_accounts("sample_data/accounts.json")
TODAY = date(2026, 11, 16)
DELIVERY = date(2026, 11, 17)


def row(sku, wine, price, qty=1, unit="case", notes="", file="order1.txt", account="Harbor & Vine Cedar Hills (CH)"):
    return {"file": file, "account": account, "sku": sku, "wine": wine, "quantity": qty,
            "unit": unit, "unit_price": Decimal(str(price)), "line_total": Decimal("0"), "notes": notes}


ROWS = [
    row("200107", "Cantina Brenvalli Nero d'Avola Rosso Sole 2024 (750ml/12)", 128),
    row("200208", "Maison Vireaux Cremant de Bourgogne Brut NV (750ml/12)", 320),
]


def test_format_money():
    assert format_money(Decimal("128")) == "$128"
    assert format_money(Decimal("10.67")) == "$10.67"
    assert format_money(Decimal("1200")) == "$1,200"


def test_line_matches_the_template():
    assert format_line(ROWS[1]) == "200208 Maison Vireaux Cremant de Bourgogne Brut NV (750ml/12) - 1cs @ $320"


def test_bottle_line():
    assert format_line(row("1", "Wine (750ml/12)", "10.67", qty=6, unit="bottle")).endswith("- 6btl @ $10.67")


def test_when_phrase():
    assert when_phrase(DELIVERY, TODAY) == "tomorrow"
    assert when_phrase(date(2026, 11, 19), TODAY) == "Thursday 11/19"


def test_draft_follows_the_template():
    text = build_draft(ROWS, DELIVERY, "desk@example.com", ACCOUNTS, today=TODAY)
    assert text.startswith("To: desk@example.com\nSubject: Harbor & Vine CH - New Order - 11/17/26\n")
    assert "Hi, Please send the following for tomorrow." in text
    assert "200208 Maison Vireaux Cremant de Bourgogne Brut NV (750ml/12) - 1cs @ $320" in text
    assert text.rstrip().endswith("John Smith\nWine Consultant, NYC")
    assert "CHECK BEFORE SENDING" not in text


def test_signature_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("ORDER_SIGNATURE", "Pat Lee\\nBuyer, Anytown")
    text = build_draft(ROWS, DELIVERY, "desk@example.com", ACCOUNTS, today=TODAY)
    assert text.rstrip().endswith("Pat Lee\nBuyer, Anytown")


def test_assumed_vintage_is_called_out_at_the_top():
    rows = [row("200103", "Cantina Brenvalli Primitivo di Puglia 2023 (750ml/12)", 104,
                notes="vintage assumed: 2023 (oldest in stock)")]
    text = build_draft(rows, DELIVERY, "desk@example.com", ACCOUNTS, today=TODAY)
    assert text.startswith("CHECK BEFORE SENDING")
    assert "vintage assumed: 2023" in text.split("----------")[0]


def test_write_drafts_one_file_per_order(tmp_path):
    rows = ROWS + [row("1", "Quinta do Vale Verde Vinho Verde 2025 (750ml/12)", 144, file="order7.txt", account="Harbor & Vine Marina (MR)")]
    written = write_drafts(rows, tmp_path / "drafts", DELIVERY, ACCOUNTS, "desk@example.com", today=TODAY)
    assert sorted(p.name for p in written) == ["order1_CH.txt", "order7_MR.txt"]
    assert "Harbor & Vine MR - New Order" in (tmp_path / "drafts" / "order7_MR.txt").read_text()
