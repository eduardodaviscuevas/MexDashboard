# Task: Build a self-updating Mexico economy dashboard with an industrial real estate panel

## Purpose
Build a static, web-based dashboard that monitors Mexico's economy, with a focus on the question:
"Is Mexico's industrial / nearshoring story holding up under peso and interest-rate pressure?"
It must refresh automatically on a schedule, be verifiable against original sources, and be easy to extend later. I will keep using it beyond this assignment, so favor a clean, config-driven design over quick hacks.

## Stack and hosting
- Python 3.11+ for data fetching; plain HTML/JS with Plotly.js (or similar) for the front end. No server.
- Host on GitHub Pages. Schedule refreshes with a GitHub Actions cron workflow (daily) plus manual `workflow_dispatch`.
- API tokens (Banxico SIE, INEGI) go in GitHub repo secrets and local env vars. Never commit tokens. Provide a `.env.example`.

## Architecture requirements
1. `config/series.yaml`: the single source of truth. For each series: id, display name, panel, source organization, source series ID, API endpoint, units, frequency, transformation (if any), sample start date, and the URL of the official source page. Adding a series must require only a YAML edit.
2. `src/fetch.py`: reads the config, pulls each series, writes tidy CSVs to `data/` (one per series: date, value, plus a derived column if transformed).
3. `data/status.json`: for each series, record `latest_observation_date`, `last_fetch_attempt_utc`, `last_successful_fetch_utc`, `status` (ok/error), and an error message if any. Also include a top-level `last_successful_refresh_utc` for the whole run.
4. Failure behavior: if a series fails to fetch, KEEP its previous data and previous successful-refresh timestamp, mark it as stale with the error, and do not report a successful refresh for it. The workflow should still publish the other series. Never let a failed fetch silently update a "last refreshed" timestamp.
5. Front end reads `data/*.csv` and `status.json` only. Each chart must show: title, units, frequency, source (linked to the official page), latest observation date, and any transformation note. Separately, display the "Last successful refresh" date and time (UTC, and also local time Mexico City) at the top of the dashboard, clearly distinct from each chart's "Latest observation" date.
6. Show a visible STALE badge on any chart whose latest observation is older than expected for its frequency, or whose last fetch failed.

## Panel A: Core macro indicators (official, fully automated)
Use only primary sources (Banxico, INEGI, or other official statistical agencies). Choose these 6 series. You must look up the exact series IDs in the official catalogs/APIs and record them in the config; do NOT guess IDs. Verify each by fetching it and confirming the name and units match.
1. USD/MXN exchange rate, Banxico "FIX" rate, daily. State the quote convention on the chart: pesos per 1 US dollar (an increase means the peso depreciated). 
2. Banxico policy rate (overnight interbank target rate), event-driven; show as a step line.
3. CPI inflation, headline and core, INEGI. Transformation: compute year-over-year % change from the index; state the base period of the index.
4. Economic activity: IGAE (INEGI), monthly. Show y/y % change, and optionally the index rebased to 100 at a stated date.
5. Manufacturing / industrial production (INEGI), monthly. Same transformation notes as above.
6. Merchandise trade: manufacturing exports or the trade balance (INEGI/Banxico), monthly. State whether it is seasonally adjusted and the currency/units.
Optional 7th/8th if clean: unemployment rate (INEGI ENOE) and remittances (Banxico).
Sample period: at least 10 years of history (start Jan 2015 or earlier where available) so recent moves can be read against the pre-pandemic, pandemic, and nearshoring-era context.

## Panel B: Industrial real estate (official proxies, fully automated)
Add a clearly separated panel titled "Industrial real estate: demand and supply proxies". Choose 2 to 3 of these, whichever have usable official APIs/data, and justify the choice in the README:
- Industrial construction activity or construction value by type of work (INEGI construction survey, ENEC) or construction fixed investment (INEGI). Check what granularity is available and document it.
- Formal manufacturing employment (IMSS open data).
- U.S.-Mexico border truck crossings (U.S. Bureau of Transportation Statistics Border Crossing Entry Data, via data.bts.gov API), e.g., Laredo and other major ports, monthly.
- FDI by sector/state (Secretaría de Economía), quarterly, if machine-readable.
Each follows the same chart metadata rules and is verified like Panel A.

## Panel C: Industrial market data (manual, quarterly, NOT official)
Add a third panel titled "Market data (broker reports, manual quarterly update)". Rules:
- Data lives in `data/manual/market_data.csv` with columns: market, quarter, vacancy_rate_pct, asking_rent_usd_sqft_yr (or the unit the source uses), source_name, source_url, report_publication_date, notes.
- Use ONE broker consistently (e.g., CBRE, Colliers, JLL, Cushman & Wakefield, or Newmark; whichever has publicly accessible quarterly Mexico industrial reports) for 3 markets, such as Monterrey, Bajío, and Tijuana or Ciudad Juárez. Do not mix brokers on one chart; their market definitions differ.
- Do not scrape PDFs automatically. Pre-fill the CSV with the most recent available quarters that you can actually read from the public report, and cite the exact source page; if you cannot find or read a value, leave it out rather than estimate it. Mark any value you could not verify.
- Visibly label this panel "Non-official, broker survey, manually updated" and display the age of the latest data point in days. The scheduled refresh must not claim this panel was refreshed automatically.
- Include a short `docs/UPDATING_MARKET_DATA.md` explaining how to add a new quarter.

## Verification (must be done and documented)
1. Create `verify/spot_checks.csv` with, for at least one observation per series (including each Panel C market): series id, date, value shown on the dashboard, value on the original source page, URL, date checked, and pass/fail.
2. Write `verify/check.py` that loads the dashboard CSVs and compares them to the values in spot_checks.csv with a stated tolerance, printing a pass/fail table. Where I must enter the original-source value by hand because the source page cannot be read programmatically, leave a clearly marked blank for me to fill in, and say so. Do not invent "original source" values.
3. Run a refresh end to end (locally and via the GitHub Actions workflow) and save the log to `verify/refresh_log.txt`. A refresh that finds no new data still counts as successful, but the log must show that every series was fetched and its status recorded.
4. Take a screenshot of the finished dashboard showing the "last successful refresh" timestamp and the latest-observation dates (e.g., using Playwright), saved to `verify/dashboard.png`.
5. Report any series where the dashboard and source disagree, and explain why (revisions, seasonal adjustment, rounding).

## Deliverables in the repo
- Working dashboard (GitHub Pages URL or `docs/` folder), the Actions workflow, and the config/fetch/front-end code.
- `README.md` with: purpose, series table (name, units, frequency, source, series ID, transformation), exchange-rate convention, how to run locally, how scheduling works, and how to add a series.
- `PROMPT.md` containing this prompt verbatim.
- `verify/` folder with the spot-check table, log, and screenshot.

## Working style
- Before building, list the exact series you plan to use, with IDs and URLs, and flag any that you couldn't confirm. Then build.
- If an API requires a token I haven't provided, stop and tell me what to obtain and where to put it; don't substitute a secondary source.
- Use only official or clearly labeled sources. If you can't find a primary-source series that fits, say so and propose an alternative rather than silently swapping.
- Keep the code simple and readable. Comment the transformations.
