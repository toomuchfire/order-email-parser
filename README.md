# Order Email Parser and Validator

Wine reps get orders as casual emails: abbreviated names, typos, no item numbers, the account buried in a subject line or signature. Someone has to decode each one, find the right item numbers, check the order minimum, and type up a clean order for the order desk.

This project does that first pass automatically. It reads an order email, matches every line to the approved wine list, checks the order against the business rules, and writes a ready-to-send draft. Anything it is not sure about goes to a review file instead of being guessed.

All data in this repo is fictional. The wines, producers, prices, stores and people in `sample_data/` are invented.

## How it works

```
order email (.txt)
      |
      v
1. AI reads it            finds the account, matches each line to a catalog item number,
                          marks lines that are returns or questions instead of orders
      |
      v
2. Plain-code rules       normalize the account, settle known ambiguities (Riserva, vintage)
      |
      v
3. Validator              checks every line and the order minimum
      |
      +--> orders_clean.csv + a draft email for each clean order
      +--> needs_review.csv   with the reason, for a person to resolve
      +--> inquiries.csv      returns and questions a person must answer
```

The split is deliberate. The AI is good at reading messy human writing, so it does the reading and matching. It never decides whether an order is acceptable and it never sees prices. Prices, totals, the minimum and every business rule live in ordinary code that can be tested and always gives the same answer.

## Business rules

- **Order minimum:** $300 or 4 cases, whichever comes first. Bottles count as a fraction of a case.
- **Prices** are per case. A bottle price is the case price divided by the pack size, read from the item description like `(750ml/12)`.
- **Accounts:** a short list in `accounts.json`. Every spelling of a store name is normalized to one of them, and anything else is flagged.
- **Riserva:** if the customer does not say Riserva, the non-Riserva wine is meant.
- **Vintage:** if the customer gives no vintage, take the oldest vintage that is in stock (from `data/stock.csv`). If they name a vintage, use it.
- **Returns and questions:** lines like "need to return..." or "checking in re: ..." are never priced as orders. They go to `inquiries.csv`.
- **Stray numbers:** a line like "1 case 1 Chablis" is flagged, since a second number may be a typo.

Without a stock file, lines with an unstated vintage are flagged instead of guessed.

## Quick start

Needs Python 3.9 or newer and an Anthropic API key.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then put your key in .env
python main.py --demo       # runs on the fictional sample_data/
```

The demo reads `sample_data/orders/` and writes to `demo_output/`. Compare the result with `sample_data/EXPECTED.md`: 14 sample orders, 8 clean and 6 flagged, each flagged one for a specific reason.

To run on your own data, point it at your files:

```
python main.py --catalog data/approved_wines.csv --stock data/stock.csv \
               --accounts accounts.json --orders-dir orders
```

Other options: `--dry-run` (show what would be sent, make no API calls), `--limit N`, `--delivery-date YYYY-MM-DD` (default is tomorrow), `--output-dir`. Set `ORDER_DESK_EMAIL` in `.env` to address the drafts.

## Outputs

| File | What it holds |
|---|---|
| `orders_clean.csv` | One row per order line: item number, wine, quantity, unit price, line total, notes |
| `drafts/` | One draft email per clean order, built from `reply_template.txt`. Nothing is sent |
| `needs_review.csv` | Orders that need a person, with the reasons and the extracted data |
| `inquiries.csv` | Returns and questions to answer by hand |
| `run.log` | What happened on each email |

When the stock rule picks a vintage on its own, the draft starts with a "CHECK BEFORE SENDING" note naming the wine.

## Project layout

```
main.py          run the pipeline
order_parser.py  AI step: prompt, JSON parsing, one retry on a bad reply
rules.py         account, Riserva, vintage, inquiry rules and the stock list
validators.py    line checks and the order minimum
catalog.py       load the price list
drafts.py        build the draft emails (from reply_template.txt)
gmail_reader.py  optional: read unread mail over IMAP instead of files
sample_data/     fictional catalog, stock, accounts and 14 test emails
test_*.py        98 tests
```

Run the tests with `python -m pytest`. They need no API key.

## AI review notes

This project was built with an AI assistant (Claude), and it uses an AI model at run time. Here is where a person is still in charge.

**What the AI does at run time**
- Reads the email and proposes a match for each line. Each match carries a confidence and a list of alternatives.
- Everything else is plain code. The model's answer is checked: the matched wine must share a word with what the customer wrote, the item number must exist, and the reply must be valid JSON in the expected shape (one retry, then the email goes to review).
- One bad email never stops a batch. Errors, timeouts and unreadable replies all end up in `needs_review.csv`.
- The model sees the email text plus item numbers and wine names. It never sees prices. The email text goes to the AI provider, so scrub real contact details from real emails first (the sample orders show the format).

**What a person reviews**
- Everything in `needs_review.csv` and `inquiries.csv`.
- The "CHECK BEFORE SENDING" notes on drafts where a vintage was assumed.
- Every draft before it is sent. The program never sends email.

**What went wrong while building it**
- The first version read only the first part of the model's reply and crashed when the reply began with a reasoning block. The fix was to join only the text parts.
- An early match check flagged a correct match because it keyed on a generic word. It now compares the customer's words against the wine name.
- Test data written without care created an ambiguity nobody intended (two similar Chablis). The parser correctly flagged it, and the data was fixed.
- Real orders showed cases the first design missed: returns inside orders, and "checking in" lines about sold-out wines. Both became explicit rules with tests.

It was also run against 10 real order emails (not included here). All the clean ones were verified by hand against the original emails, and every flagged one was flagged for a real reason.

## Limits

- Matches are only as good as the catalog. A wine that is not on the list is flagged, never invented.
- The stock rule needs a stock file. Without one, unstated vintages are flagged.
- Reads plain-text emails. Attachments and images are not handled.
- It drafts. It does not send, and it does not enter anything into an order system.
