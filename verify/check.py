"""
Compare the dashboard's data files with values read from the ORIGINAL source pages.

    python verify/check.py            # print the pass/fail table
    python verify/check.py --write    # also write dashboard_value / pass_fail / date_checked back into spot_checks.csv

spot_checks.csv columns
  panel          A | B | C
  series_id      data/<series_id>.csv for panels A/B; the market name for panel C
  date           YYYY-MM-DD (panels A/B) or quarter like 2026Q2 (panel C)
  column         value | yoy_pct (A/B) or a column of data/manual/market_data.csv (C)
  source_value   the number as printed on the source page, in the SAME units as the dashboard column.
                 BLANK = not yet checked by hand; check.py reports it as PENDING, never as a pass.
  tolerance      max allowed |dashboard - source|. Rule: half a unit of the last digit the source prints
                 (e.g. source prints 3.0 -> tolerance 0.05), because sources round and we do not.
  source_url, source_location   where exactly the number was read
  dashboard_value, pass_fail, date_checked   filled by --write

Exit code 1 if any row FAILS (PENDING rows do not fail the run but are listed).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPOT = ROOT / "verify" / "spot_checks.csv"
DATA = ROOT / "data"
MANUAL = DATA / "manual" / "market_data.csv"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def dashboard_value(row: dict) -> float | None:
    """Look up the value the dashboard shows for this spot check (None if missing)."""
    if row["panel"] == "C":
        for r in read_csv(MANUAL):
            if r["market"] == row["series_id"] and r["quarter"] == row["date"]:
                v = r.get(row["column"], "")
                return float(v) if v not in ("", None) else None
        return None
    path = DATA / f"{row['series_id']}.csv"
    if not path.exists():
        return None
    for r in read_csv(path):
        if r["date"] == row["date"]:
            v = r.get(row["column"], "")
            return float(v) if v not in ("", None) else None
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # market names contain accents (Windows consoles)
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write results back into spot_checks.csv")
    args = ap.parse_args()

    rows = read_csv(SPOT)
    fieldnames = list(rows[0].keys())
    n_fail = n_pending = 0
    print(f"{'panel':<5} {'series':<22} {'date':<10} {'column':<24} {'dashboard':>14} {'source':>14} {'|diff|':>10} {'tol':>8}  result")
    print("-" * 125)
    for row in rows:
        dv = dashboard_value(row)
        sv = row["source_value"].strip()
        tol = float(row["tolerance"] or 0)
        if dv is None:
            result, diff = "FAIL (value missing from dashboard data)", None
        elif sv == "":
            result, diff = "PENDING (source value must be entered by hand)", None
        else:
            diff = abs(dv - float(sv))
            result = "PASS" if diff <= tol + 1e-12 else "FAIL"
        n_fail += result.startswith("FAIL")
        n_pending += result.startswith("PENDING")
        print(f"{row['panel']:<5} {row['series_id'][:22]:<22} {row['date']:<10} {row['column'][:24]:<24} "
              f"{'' if dv is None else f'{dv:,.6g}':>14} {sv:>14} {'' if diff is None else f'{diff:.4g}':>10} {tol:>8g}  {result}")
        if args.write:
            row["dashboard_value"] = "" if dv is None else f"{dv:.6f}".rstrip("0").rstrip(".")
            row["pass_fail"] = result.split(" ")[0]
            if sv != "":
                row["date_checked"] = row["date_checked"] or date.today().isoformat()

    print("-" * 125)
    print(f"{len(rows)} checks: {len(rows) - n_fail - n_pending} pass, {n_fail} fail, {n_pending} pending manual entry")
    if args.write:
        with SPOT.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {SPOT}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
