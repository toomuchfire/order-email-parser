"""Turn a raw order email into structured JSON using an AI model.

The model reads the email, finds the account, and matches each line to an
item number from the approved wine list (names only, no prices). It never
decides whether an order is acceptable: validators.py does that in plain code,
and anything the model is unsure about is flagged for a person to review.
"""

import json
import logging
import re

try:
    import anthropic
    API_ERRORS = (anthropic.APIError,)
except ImportError:  # lets tests run without the SDK installed
    anthropic = None
    API_ERRORS = ()

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-5-5"

PROMPT_TEMPLATE = """You read wine order emails for a wine distributor and return structured data.
Reply with ONE JSON object and nothing else, in exactly this shape:

{{"is_order": true or false,
 "account": "the customer's business name, or null",
 "account_source": "subject" or "signature" or "sender" or null,
 "lines": [
   {{"text": "the line exactly as the customer wrote it",
    "kind": "order" or "inquiry" or "return",
    "quantity": a number, or null if none is given,
    "unit": "case" or "bottle",
    "sku": "item number from the approved list below, or null",
    "confidence": "high" or "low",
    "alternatives": ["other item numbers from the list that could also match"]}}
 ]}}

Rules:
- kind is "inquiry" for a line where the customer is only asking about a wine (for example under
  "checking in re:", "do you have", "any update on", "is X back"). Those are questions, not orders.
  kind is "return" for a line where the customer says they need to return, send back, or were
  shorted or sent the wrong wine ("need to return", "didn't receive"). Returns are never new orders,
  even when the line starts with a quantity like "1cs".
  Every other line is kind "order".
- Customers abbreviate and never give item numbers. Match each line to the approved list.
- Only use item numbers that appear in the list. Never invent one.
- If exactly one wine clearly fits, set sku to it, confidence "high", alternatives [].
- If several wines fit (for example the same wine in different vintages, or a short name that matches
  more than one), set confidence "low", put your best guess in sku (or null) and ALL plausible item
  numbers in alternatives.
- If nothing in the list fits, set sku to null and alternatives [].
- unit is "bottle" only if the line says bottles, btls or btl. Otherwise it is "case".
- Copy quantities as written. Convert number words to digits. Do not guess a missing quantity.
- The account is usually in the subject line. If not, look at the signature, then the sender address.
- Ignore forwarded or quoted history unless it holds the order.
- If the email is not an order, set is_order to false and lines to [].
- Output JSON only. No markdown, no commentary.

Approved wine list (item number | name):
{catalog_listing}"""


class ExtractionError(Exception):
    """The model could not be reached or never returned usable JSON."""


def catalog_listing(catalog):
    """Item numbers and names only. No prices go to the model."""
    return "\n".join(f"{sku} | {wine['name']}" for sku, wine in catalog.items())


def build_system_prompt(catalog):
    return PROMPT_TEMPLATE.format(catalog_listing=catalog_listing(catalog))


def parse_json_reply(text):
    """Pull a JSON object out of a model reply, tolerating ```json fences."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    return json.loads(cleaned[start:end + 1])


def check_shape(data):
    """Raise ValueError if the reply is JSON but not the shape we asked for."""
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    if "is_order" not in data or not isinstance(data.get("lines"), list):
        raise ValueError("reply is missing 'is_order' or 'lines'")
    for line in data["lines"]:
        if not isinstance(line, dict):
            raise ValueError("a line is not an object")
    return data


def extract_order(email_text, client, catalog, model=DEFAULT_MODEL, max_attempts=2):
    """Return the parsed order dict. Retries once if the reply is malformed."""
    system_prompt = build_system_prompt(catalog)
    messages = [{"role": "user", "content": f"Extract the order from this email:\n\n{email_text}"}]
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.messages.create(
                model=model, max_tokens=4000, system=system_prompt, messages=messages
            )
        except API_ERRORS as exc:  # the SDK already retried timeouts and rate limits
            raise ExtractionError(f"API call failed: {exc}") from exc

        # Replies can start with a "thinking" block, so join only the text blocks.
        reply = "".join(b.text for b in response.content if hasattr(b, "text"))
        try:
            return check_shape(parse_json_reply(reply))
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning("Attempt %d: bad reply (%s)", attempt, exc)
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "That was not valid JSON in the required shape. "
                                            "Reply again with the JSON object only."},
            ]

    raise ExtractionError(f"No usable JSON after {max_attempts} attempts: {last_error}")


def make_client():
    """Create the API client. Reads ANTHROPIC_API_KEY from the environment."""
    if anthropic is None:
        raise ExtractionError("The 'anthropic' package is not installed. Run: pip install -r requirements.txt")
    return anthropic.Anthropic(timeout=30.0, max_retries=2)
