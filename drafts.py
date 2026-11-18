"""Turn clean orders into draft emails to the order desk.

One text file per order, built from reply_template.txt. Nothing is sent: the files
are for a person to read, copy and send. Only clean orders get a draft; anything
flagged stays in needs_review.csv until someone resolves it.
"""

import os
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from rules import account_short

TEMPLATE_PATH = Path(__file__).with_name("reply_template.txt")
UNIT_LABEL = {"case": "cs", "bottle": "btl"}
DEFAULT_SIGNATURE = "John Smith\nWine Consultant, NYC"


def format_money(value):
    """128 -> '$128', 10.67 -> '$10.67'."""
    text = f"{Decimal(str(value)):,.2f}"
    return "$" + (text[:-3] if text.endswith(".00") else text)


def format_line(row):
    unit = UNIT_LABEL.get((row.get("unit") or "case").lower(), "cs")
    return f"{row['sku']} {row['wine']} - {row['quantity']}{unit} @ {format_money(row['unit_price'])}"


def when_phrase(delivery, today):
    if delivery == today + timedelta(days=1):
        return "tomorrow"
    return f"{delivery.strftime('%A')} {delivery.month}/{delivery.day}"


def build_draft(rows, delivery, to_address, accounts, today=None, template=None, signature=None):
    """Return the draft text for one order (all rows share a file and an account)."""
    today = today or date.today()
    template = template if template is not None else TEMPLATE_PATH.read_text(encoding="utf-8")
    account = rows[0]["account"]
    short = account_short(account, accounts)
    subject = f"{accounts['subject_prefix']} {short} - New Order - {delivery.strftime('%m/%d/%y')}"
    signature = signature or os.environ.get("ORDER_SIGNATURE", DEFAULT_SIGNATURE).replace("\\n", "\n")
    body = template.format(
        signature=signature, to=to_address, subject=subject, when=when_phrase(delivery, today),
        lines="\n".join(format_line(r) for r in rows),
    )
    notes = [r["notes"] for r in rows if r.get("notes")]
    if notes:
        checks = "\n".join(f"  - {r['wine']}: {r['notes']}" for r in rows if r.get("notes"))
        body = f"CHECK BEFORE SENDING (delete this block):\n{checks}\n\n----------\n\n{body}"
    return body


def write_drafts(clean_rows, out_dir, delivery, accounts, to_address=None, today=None):
    """Write one draft per clean order. Returns the list of files written."""
    to_address = to_address or os.environ.get("ORDER_DESK_EMAIL", "orders@example.com")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_file = {}
    for row in clean_rows:
        by_file.setdefault(row["file"], []).append(row)
    written = []
    for name, rows in by_file.items():
        short = account_short(rows[0]["account"], accounts)
        path = out_dir / f"{Path(name).stem}_{short}.txt"
        path.write_text(build_draft(rows, delivery, to_address, accounts, today), encoding="utf-8")
        written.append(path)
    return written
