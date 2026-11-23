# Updating Panel C (broker market data)

Panel C is **non-official, broker survey data, entered by hand once a quarter**.
The scheduled refresh never touches it, and the dashboard says so.

## Rules

1. **One broker only.** The panel uses **CBRE Research "Industrial Figures"** reports
   (public pages at <https://www.cbre.com.mx/reportes-de-mercado>). Brokers define markets,
   building size cut-offs and vacancy differently, so do not add another broker's numbers
   to the same columns. To switch brokers, replace every row and say so in the README.
2. **Only type numbers you can read in the report.** If the report does not print a value
   (for example it says "flat quarter-over-quarter" without the figure), leave the cell blank.
   Never estimate, interpolate, or infer.
3. **Use the measure the report prints**: market-wide (overall) vacancy, not Class A;
   average asking rent in **US$ per sq. ft. per year** (CBRE's unit for these markets).
   If a report only gives US$/m²/month, leave the rent blank and put the figure in `notes`.
4. **Cite the exact page** (report web page or PDF link) and the publication date shown on it.

## Steps

1. Open the broker's report for the new quarter.
2. Add one row per market to `data/manual/market_data.csv`:

   | column | example | notes |
   |---|---|---|
   | `market` | `Saltillo` | keep the existing spelling so the chart line continues |
   | `quarter` | `2026Q3` | format `YYYYQn` |
   | `vacancy_rate_pct` | `1.9` | percent, as printed; blank if not printed |
   | `asking_rent_usd_sqft_yr` | `7.48` | as printed; blank if not printed |
   | `source_name` | `CBRE Research (Saltillo Industrial Figures Q3 2026)` | |
   | `source_url` | report page or PDF URL | |
   | `report_publication_date` | `2026-10-06` | as shown on the page; blank if none |
   | `verification` | `verified` | `verified` only if you read the number yourself on the page; otherwise `NEEDS USER CONFIRMATION` |
   | `notes` | quote the sentence/label the number came from | |

   Fields containing commas must be wrapped in double quotes.
3. Add a row to `verify/spot_checks.csv` for at least one new value (panel `C`, `series_id` = market,
   `date` = quarter, `column` = the column name, `source_value` = the number on the page), then run:

   ```
   python verify/check.py --write
   ```
4. Open the dashboard locally (`python -m http.server 8000`, then http://localhost:8000) and check
   that Panel C shows the new quarter and the "latest data point" age has reset.
5. Commit and push. The next workflow run republishes the site; it does not change these values.

## Current state (2026-11-23)

* Ciudad Juárez 2026Q2 vacancy (6.9%) was read from PDF text whose layout was garbled. It is marked
  `NEEDS USER CONFIRMATION`; please confirm it against page 1 of the PDF.
* Ciudad Juárez 2026Q3: the web summary only says vacancy was "flat"; the PDF could not be opened
  by the automated tools, so the value is blank. Please fill it from the PDF.
* Bajío and Saltillo: the most recent public CBRE reports are Q2 2025. Their numbers were read from the
  report web pages and are `verified`. Newer quarters may only be in PDFs; add them when available.
