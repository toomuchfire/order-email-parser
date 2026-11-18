"""Read order emails, extract them with an AI model, validate against the catalog.

Usage:
    python main.py                  process everything in orders/
    python main.py --dry-run        show what would be sent, make no API calls
    python main.py --limit 3        only process the first 3 emails
    python main.py --source gmail   read unread mail from the Gmail test inbox
    python main.py --source gmail --mark-read   ...and mark each one read afterwards
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from catalog import load_catalog
from drafts import write_drafts
from gmail_reader import GmailError, GmailInbox
from order_parser import DEFAULT_MODEL, ExtractionError, extract_order, make_client
from rules import (apply_line_rules, canonical_account, load_accounts, load_stock,
                   split_inquiries, subject_line)
from validators import line_amounts, unit_price, validate_order

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("orders")
CLEAN_FIELDS = ["file", "account", "sku", "wine", "quantity", "unit", "unit_price", "line_total", "notes"]
INQUIRY_FIELDS = ["file", "account", "kind", "text", "wine"]
REVIEW_FIELDS = ["file", "account", "reasons", "extracted_json"]


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler("run.log")],
    )


def process_email(name, text, catalog, client, model, stock=None, accounts=None):
    """Return ('clean' | 'review', rows, inquiries). Never raises for a bad email."""
    try:
        order = extract_order(text, client, catalog, model)
    except ExtractionError as exc:
        return "review", [{"file": name, "account": "", "reasons": str(exc), "extracted_json": ""}], []

    if not order.get("is_order"):
        return "review", [{"file": name, "account": order.get("account") or "",
                           "reasons": "not an order", "extracted_json": json.dumps(order)}], []

    # Plain-code rules: normalize the account, set aside inquiries, settle known ambiguities.
    written_as = order.get("account")
    order["account"] = canonical_account(written_as, subject_line(text), text, accounts=accounts)
    order, inquiry_lines = split_inquiries(order)
    order = apply_line_rules(order, catalog, stock)
    inquiries = []
    for line in inquiry_lines:
        sku = str(line.get("sku") or "").strip()
        inquiries.append({"file": name, "account": order["account"] or "", "kind": line.get("kind"), "text": line.get("text", ""),
                          "wine": catalog[sku]["name"] if sku in catalog else ""})

    ok, reasons = validate_order(order, catalog)
    if not ok:
        if not order["account"] and written_as:
            shorts = ", ".join(a["short"] for a in accounts["accounts"].values())
            reasons = [f"account '{written_as}' is not one of the {len(accounts['accounts'])} accounts ({shorts})"
                       if r == "account not identified" else r for r in reasons]
        return "review", [{"file": name, "account": order["account"] or written_as or "",
                           "reasons": "; ".join(reasons), "extracted_json": json.dumps(order)}], inquiries

    rows = []
    for line in order["lines"]:
        wine = catalog[str(line["sku"]).strip()]
        unit = (line.get("unit") or "case").lower()
        quantity = int(Decimal(str(line["quantity"]).strip()))
        dollars, _ = line_amounts(line, catalog)
        rows.append({"file": name, "account": order["account"], "sku": str(line["sku"]).strip(),
                     "wine": wine["name"], "quantity": quantity, "unit": unit,
                     "unit_price": unit_price(wine, unit), "line_total": dollars.quantize(Decimal("0.01")),
                     "notes": line.get("note", "")})
    return "clean", rows, inquiries


def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--orders-dir", default="orders")
    args.add_argument("--catalog", default="data/approved_wines.csv")
    args.add_argument("--accounts", default="accounts.json", help="accounts file (see sample_data/accounts.json)")
    args.add_argument("--output-dir", default=".", help="where the CSVs and drafts/ are written")
    args.add_argument("--demo", action="store_true",
                      help="run on the fictional sample_data/ (catalog, stock, accounts, orders) into demo_output/")
    args.add_argument("--delivery-date", help="delivery date for the draft emails, YYYY-MM-DD (default: tomorrow)")
    args.add_argument("--stock", default="data/stock.csv", help="optional in-stock list (item number + in_stock)")
    args.add_argument("--source", choices=["files", "gmail"], default="files")
    args.add_argument("--mark-read", action="store_true", help="with --source gmail, mark processed mail as read")
    args.add_argument("--dry-run", action="store_true")
    args.add_argument("--limit", type=int)
    opts = args.parse_args(argv)

    if opts.demo:
        opts.catalog, opts.stock, opts.accounts = ("sample_data/catalog.csv", "sample_data/stock.csv",
                                                    "sample_data/accounts.json")
        opts.orders_dir, opts.output_dir = "sample_data/orders", "demo_output"
    out = Path(opts.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    setup_logging()
    catalog = load_catalog(opts.catalog, encoding="utf-8" if opts.demo else "cp1252")
    accounts = load_accounts(opts.accounts)
    stock = load_stock(opts.stock)
    if stock is None:
        logger.info("No stock file at %s: orders with an unstated vintage will be flagged", opts.stock)
    else:
        logger.info("Loaded stock list: %d item(s) in stock", len(stock))

    inbox, uids = None, []
    if opts.source == "gmail":
        address, password = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
        if not address or not password:
            logger.error("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env to use --source gmail")
            return 1
        try:
            inbox = GmailInbox(address, password).__enter__()
            items = [(f"gmail_{uid}", text) for uid, text in inbox.fetch_unread(opts.limit)]
            uids = [name.removeprefix("gmail_") for name, _ in items]
        except GmailError as exc:
            logger.error("%s", exc)
            return 1
    else:
        files = sorted(p for p in Path(opts.orders_dir).iterdir() if p.suffix in {".txt", ".eml"})
        if opts.limit:
            files = files[: opts.limit]
        items = [(p.name, p.read_text(encoding="utf-8", errors="replace")) for p in files]
    logger.info("Found %d email(s) to process", len(items))

    if opts.dry_run:
        for name, text in items:
            logger.info("[dry run] would send %s (%d chars) to the model", name, len(text))
        if inbox:
            inbox.__exit__()
        return 0

    client = make_client()
    clean, review, inquiries = [], [], []
    for name, text in items:
        try:
            status, rows, asked = process_email(name, text, catalog, client, DEFAULT_MODEL, stock, accounts)
            inquiries.extend(asked)
        except Exception:  # one bad email must never stop the batch
            logger.exception("Unexpected error on %s", name)
            status, rows = "review", [{"file": name, "account": "", "reasons": "unexpected error, see run.log",
                                       "extracted_json": ""}]
        (clean if status == "clean" else review).extend(rows)
        logger.info("%s -> %s", name, status)

    if inbox:
        if opts.mark_read:
            inbox.mark_read(uids)
            logger.info("Marked %d message(s) as read", len(uids))
        inbox.__exit__()

    write_csv(out / "orders_clean.csv", CLEAN_FIELDS, clean)
    write_csv(out / "needs_review.csv", REVIEW_FIELDS, review)
    write_csv(out / "inquiries.csv", INQUIRY_FIELDS, inquiries)
    delivery = date.fromisoformat(opts.delivery_date) if opts.delivery_date else date.today() + timedelta(days=1)
    drafted = write_drafts(clean, out / "drafts", delivery, accounts)
    logger.info("Wrote %d draft email(s) to %s for delivery %s", len(drafted), out / "drafts", delivery.isoformat())
    clean_orders = len({r["file"] for r in clean})
    logger.info("Done: %d clean order(s), %d need review, %d inquiry/return line(s) for you to answer", clean_orders, len(review), len(inquiries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
