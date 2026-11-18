"""Load the Approved Wines price sheet into a dict keyed by item number (SKU)."""

import csv
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

logger = logging.getLogger(__name__)

# The sheet is saved from Excel, so it is Windows-1252, not UTF-8.
DEFAULT_ENCODING = "cp1252"
PACK_RE = re.compile(r"\(\s*[\d.]+\s*(?:ml|l|cl)\s*/\s*(\d+)\s*\)", re.IGNORECASE)


def parse_price(raw):
    """'$960 ' -> Decimal('960'). Returns None if blank or not a number."""
    cleaned = (raw or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_pack_size(description):
    """'... (750ml/12)' -> 12. Returns None if the description has no pack info."""
    match = PACK_RE.search(description or "")
    return int(match.group(1)) if match else None


def load_catalog(path, price_column="Price", encoding=DEFAULT_ENCODING):
    """Return {sku: {"name", "brand", "price", "pack_size"}}.

    Skips the contact block above the header, blank rows, and region
    divider rows (ITALY, FRANCE, ...). Rows with a missing or invalid
    price are skipped and logged. On a duplicate SKU the first row wins
    and the clash is logged, so a bad row in the sheet never silently
    overwrites a good one.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Catalog file not found: {path}")

    with path.open(newline="", encoding=encoding) as fh:
        rows = list(csv.reader(fh))

    header_idx = next(
        (i for i, row in enumerate(rows) if any(c.strip() == "Item #" for c in row)),
        None,
    )
    if header_idx is None:
        raise ValueError(f"No 'Item #' header row found in {path}")

    header = [c.strip() for c in rows[header_idx]]
    for needed in ("Item #", "Brand Name", "Item Description", price_column):
        if needed not in header:
            raise ValueError(f"Column '{needed}' missing from {path}")
    col = {name: header.index(name) for name in header if name}

    catalog = {}
    for line_no, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        row = row + [""] * (len(header) - len(row))
        sku = row[col["Item #"]].strip()
        if not sku.isdigit():  # blank row or a region divider like "ITALY"
            continue

        price = parse_price(row[col[price_column]])
        if price is None:
            logger.warning("Line %d: SKU %s skipped, no valid %s", line_no, sku, price_column)
            continue

        name = row[col["Item Description"]].strip()
        if sku in catalog:
            logger.warning(
                "Line %d: duplicate SKU %s ('%s') ignored; keeping '%s'",
                line_no, sku, name, catalog[sku]["name"],
            )
            continue

        catalog[sku] = {
            "name": name,
            "brand": row[col["Brand Name"]].strip(),
            "price": price,
            "pack_size": parse_pack_size(name),
        }

    logger.info("Loaded %d wines from %s", len(catalog), path.name)
    return catalog
