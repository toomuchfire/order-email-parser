# Expected results for the demo data

Everything in `sample_data/` is fictional: the wines, producers, prices, stores and people.
Run `python main.py --demo` and compare with this table. Results go to `demo_output/`.

| Order | Rule it exercises | Expected |
|---|---|---|
| 01 | Full wine names, NB account | clean |
| 02 | Abbreviations and a 2-case line, CH account | clean |
| 03 | "pellarini chianti" with no Riserva | clean, Chianti Classico (not the Riserva) |
| 04 | "Chianti Classico Riserva" named | clean, the Riserva |
| 05 | No vintage given, stock list applies | clean, oldest in-stock vintage, with a "vintage assumed" note (Montepulciano 2022 is sold out, so 2023) |
| 06 | Vintage named in the email | clean, the vintage asked for |
| 07 | "faurelle sancerre" matches three different wines | needs review (ambiguous) |
| 08 | A return and an inquiry mixed with order lines | clean for the 4 order lines; the return and the Barolo question go to `inquiries.csv` |
| 09 | "1 case 1 Vireaux Chablis" | needs review (stray number) |
| 10 | One $84 case | needs review (below the $300 / 4 case minimum) |
| 11 | Bottle orders mixed with cases | clean, bottles priced at 1/12 of a case |
| 12 | A wine that is not in the catalog | needs review (no match) |
| 13 | Not an order | needs review ("not an order") |
| 14 | A store that is not one of the three accounts | needs review (unknown account) |

Clean orders also get a draft email in `demo_output/drafts/`.
The AI step can occasionally differ on a messy line; anything it is unsure of should land in review, not clean.
