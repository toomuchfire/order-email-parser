"""Business rules applied in plain code after the AI has matched each line.

The AI reads the email and proposes matches. These rules, written by the person
who knows the business, settle the ambiguities that have a known answer, so the
same email always gives the same result:

- Account: the customer has a short list of accounts (accounts.json); every spelling is normalized to one of them.
- Riserva: if the customer did not say Riserva, they mean the non-Riserva wine.
- Vintage: if the customer gave no vintage, take the OLDEST vintage that is in stock.
- Inquiries: "checking in re: ..." lines are questions, not order lines.

Anything these rules cannot settle is left alone and flagged for a person.
"""

import csv
import json
import re
from pathlib import Path

SET_ASIDE_KINDS = ("inquiry", "return")  # answered by a person, never priced as an order
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
RISERVA_IN_TEXT = re.compile(r"\bris", re.IGNORECASE)  # riserva, ris
STOCK_SKU_COLUMNS = ("sku", "item #", "item#", "item", "item number")
STOCK_QTY_COLUMNS = ("in_stock", "in stock", "stock", "available", "qty", "quantity", "on hand")
YES_WORDS = {"y", "yes", "true", "in stock", "available"}


# ---------- account ----------

def load_accounts(path):
    """Read accounts.json: {"subject_prefix": "...", "accounts": {name: {"short", "patterns"}}}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Accounts file not found: {path}. Copy sample_data/accounts.json and edit it for your accounts.")
    config = json.loads(path.read_text(encoding="utf-8"))
    if not config.get("accounts"):
        raise ValueError(f"{path} has no accounts")
    return config


def canonical_account(*texts, accounts):
    """Return the one account named in the first text that names exactly one, else None.
    Pass them in order of trust: the AI's account, the subject line, the whole email."""
    for text in texts:
        found = [name for name, info in accounts["accounts"].items()
                 if any(re.search(p, text or "", re.IGNORECASE) for p in info["patterns"])]
        if len(found) == 1:
            return found[0]
    return None


def account_short(account, accounts):
    info = accounts["accounts"].get(account)
    return info["short"] if info else account


def subject_line(email_text):
    match = re.search(r"^Subject:[ \t]*(.*)$", email_text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


# ---------- inquiries ----------

def split_inquiries(order):
    """Return (order with only real order lines, list of inquiry and return lines)."""
    lines = order.get("lines") or []
    inquiries = [l for l in lines if l.get("kind") in SET_ASIDE_KINDS]
    kept = [l for l in lines if l.get("kind") not in SET_ASIDE_KINDS]
    return {**order, "lines": kept}, inquiries


# ---------- stock ----------

def _read_text(path):
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def load_stock(path):
    """Return the set of item numbers in stock, or None if there is no stock file.

    The file needs an item number column (sku or Item #) and an availability column
    (in_stock, available, qty ...). Values like yes/true/1 or a number above zero mean in stock.
    """
    if not Path(path).exists():
        return None
    reader = csv.DictReader(_read_text(path).splitlines())
    columns = {(name or "").strip().lower(): name for name in (reader.fieldnames or [])}
    sku_col = next((columns[c] for c in STOCK_SKU_COLUMNS if c in columns), None)
    qty_col = next((columns[c] for c in STOCK_QTY_COLUMNS if c in columns), None)
    if not sku_col or not qty_col:
        raise ValueError(f"{path} needs an item number column and an in_stock/qty column; "
                         f"found: {list(reader.fieldnames or [])}")
    in_stock = set()
    for row in reader:
        sku, value = (row[sku_col] or "").strip(), (row[qty_col] or "").strip().lower()
        if not sku:
            continue
        try:
            available = float(value) > 0
        except ValueError:
            available = value in YES_WORDS
        if available:
            in_stock.add(sku)
    return in_stock


# ---------- line rules ----------

def _candidates(line, catalog):
    found = []
    for sku in [line.get("sku")] + list(line.get("alternatives") or []):
        sku = str(sku).strip() if sku not in (None, "") else ""
        if sku in catalog and sku not in found:
            found.append(sku)
    return found


def _settle(line, sku, note=None):
    settled = {**line, "sku": sku, "alternatives": [], "confidence": "high"}
    if note:
        settled["note"] = note
    return settled


def _vintage(name):
    match = YEAR.search(name)
    return int(match.group()) if match else None


def _base(name):
    return " ".join(YEAR.sub("", name).split())


def resolve_line(line, catalog, stock=None):
    """Apply the Riserva and vintage rules to one order line. Returns a new line."""
    text = line.get("text") or ""
    candidates = _candidates(line, catalog)
    if len(candidates) < 2:
        return line

    # Riserva: only the wine the customer asked for by name.
    says_riserva = bool(RISERVA_IN_TEXT.search(text))
    wanted = [s for s in candidates
              if ("riserva" in catalog[s]["name"].lower()) == says_riserva]
    if 0 < len(wanted) < len(candidates):
        candidates = wanted
        if len(candidates) == 1:
            return _settle(line, candidates[0])

    # Vintage: same wine, different years.
    own_sku = str(line.get("sku") or "").strip()
    unsettled = {**line, "sku": own_sku if own_sku in candidates else None, "alternatives": candidates}
    bases = {_base(catalog[s]["name"]) for s in candidates}
    vintages = {s: _vintage(catalog[s]["name"]) for s in candidates}
    if len(bases) != 1 or None in vintages.values():
        return unsettled

    named = {int(y) for y in YEAR.findall(text)}
    by_year = [s for s in candidates if vintages[s] in named]
    if len(by_year) == 1:
        return _settle(line, by_year[0])

    oldest_first = sorted(candidates, key=lambda s: vintages[s])
    if stock is None:
        return {**unsettled, "sku": None, "alternatives": oldest_first,
                "note": "no vintage given; the oldest-in-stock rule needs data/stock.csv"}
    available = [s for s in oldest_first if s in stock]
    if not available:
        return {**unsettled, "sku": None, "alternatives": oldest_first,
                "note": "no vintage given and every vintage is out of stock"}
    pick = available[0]
    return _settle(line, pick, note=f"vintage assumed: {vintages[pick]} (oldest in stock)")


def apply_line_rules(order, catalog, stock=None):
    return {**order, "lines": [resolve_line(l, catalog, stock) for l in order.get("lines") or []]}
