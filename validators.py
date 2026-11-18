"""Check a parsed order against the Approved Wines catalog.

The AI step returns:
    {"account": "Harbor & Vine",
     "lines": [{"text": "1 Willow Ridge Sauv Blanc", "quantity": 1, "unit": "case",
                "sku": "200302", "confidence": "high", "alternatives": []}]}
Catalog prices are per case. A bottle is 1/pack_size of a case.
"""

import re
from decimal import Decimal, InvalidOperation

VALID_UNITS = {"case", "bottle"}
MIN_ORDER_DOLLARS = Decimal("300")
MIN_ORDER_CASES = Decimal("4")  # an order meets the minimum at $300 OR 4 cases
CENTS = Decimal("0.01")


def check_quantity(quantity):
    """Return a problem string, or None if quantity is a positive whole number."""
    if quantity is None or quantity == "":
        return "quantity missing"
    if isinstance(quantity, bool):
        return f"quantity '{quantity}' is not a number"
    try:
        value = Decimal(str(quantity).strip())
    except InvalidOperation:
        return f"quantity '{quantity}' is not a number"
    if value != value.to_integral_value():
        return f"quantity {value} is not a whole number"
    if value <= 0:
        return f"quantity {value} must be greater than zero"
    return None


def _tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "").replace("'", ""))


def looks_like_match(text, wine_name):
    """Sanity check on the AI's pick: some word in the customer's line must start
    a word in the wine's name ('Sauv' -> 'Sauvignon'). Catches a wrong or invented match."""
    name_tokens = _tokens(wine_name)
    return any(n.startswith(t) for t in _tokens(text) if len(t) >= 3 for n in name_tokens)


def has_stray_number(text):
    """True if a line has two or more quantity-like numbers ('1 case 1 Vireaux Chablis').
    Years (2023) and sizes (750ml) are not counted."""
    numbers = re.findall(r"(?<![A-Za-z\d])\d{1,3}(?!\d|\s?ml)", text, flags=re.IGNORECASE)
    return len(numbers) > 1


def _describe(skus, catalog):
    return "; ".join(f"{s} {catalog[s]['name']}" if s in catalog else f"{s} (not in list)" for s in skus)


def unit_price(wine, unit):
    """Price for one case or one bottle. None if a bottle price can't be worked out."""
    if unit == "case":
        return wine["price"]
    if not wine.get("pack_size"):
        return None
    return (wine["price"] / wine["pack_size"]).quantize(CENTS)


def line_amounts(line, catalog):
    """Return (dollars, cases) for a line whose sku and quantity are usable."""
    wine = catalog[str(line["sku"]).strip()]
    quantity = Decimal(str(line["quantity"]).strip())
    unit = (line.get("unit") or "case").lower()
    if unit == "bottle":
        return wine["price"] * quantity / wine["pack_size"], quantity / wine["pack_size"]
    return wine["price"] * quantity, quantity


def validate_line(line, catalog):
    """Return a list of problems for one order line (empty list means OK)."""
    problems = []
    text = (line.get("text") or "").strip()
    sku = str(line.get("sku") or "").strip()
    alternatives = [str(a).strip() for a in (line.get("alternatives") or []) if str(a).strip() != sku]

    if not sku:
        if alternatives:
            note = line.get("note")
            lead = f"ambiguous '{text}' ({note})" if note else f"ambiguous '{text}'"
            problems.append(f"{lead}, could be: {_describe(alternatives, catalog)}")
        else:
            problems.append(f"could not match '{text}' to an approved wine")
    elif sku not in catalog:
        problems.append(f"'{text}' matched item {sku}, which is not in the approved list")
    else:
        wine = catalog[sku]
        if not looks_like_match(text, wine["name"]):
            problems.append(f"'{text}' does not look like {wine['name']}")
        elif alternatives:
            problems.append(
                f"ambiguous '{text}', matched {wine['name']} but could also be: "
                f"{_describe(alternatives, catalog)}"
            )
        elif line.get("confidence") != "high":
            problems.append(f"low-confidence match: '{text}' -> {wine['name']}")

    problem = check_quantity(line.get("quantity"))
    if problem:
        problems.append(problem)
    elif has_stray_number(text):
        problems.append(f"'{text}' has more than one number: check the quantity")

    unit = (line.get("unit") or "case").lower()
    if unit not in VALID_UNITS:
        problems.append(f"unit '{line.get('unit')}' is not case or bottle")
    elif unit == "bottle" and sku in catalog and not catalog[sku].get("pack_size"):
        problems.append(f"cannot price bottles of {catalog[sku]['name']}: pack size unknown")
    return problems


def validate_order(order, catalog):
    """Return (is_valid, reasons). Line problems are prefixed with the line number."""
    reasons = []
    if not (order.get("account") or "").strip():
        reasons.append("account not identified")

    lines = order.get("lines") or []
    if not lines:
        reasons.append("no order lines found")

    for number, line in enumerate(lines, start=1):
        for problem in validate_line(line, catalog):
            reasons.append(f"line {number}: {problem}")

    if lines and not reasons:  # only judge the total once every line is sound
        dollars = sum((line_amounts(l, catalog)[0] for l in lines), Decimal(0))
        cases = sum((line_amounts(l, catalog)[1] for l in lines), Decimal(0))
        if dollars < MIN_ORDER_DOLLARS and cases < MIN_ORDER_CASES:
            reasons.append(
                f"below order minimum ($300 or 4 cases): "
                f"${dollars.quantize(CENTS)}, {cases.quantize(CENTS)} cases"
            )
    return (not reasons, reasons)
