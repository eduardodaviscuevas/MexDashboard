"""
Refresh every series in config/series.yaml.

    python src/fetch.py                 # refresh all series
    python src/fetch.py --only igae     # refresh one series (comma-separate several)

For each series:
  * fetch from the official API, validate, apply the configured transformation
  * on success: rewrite data/<id>.csv and update its entry in data/status.json
  * on failure: KEEP the previous CSV and the previous last_successful_fetch_utc,
    set status="error" with the message. Nothing claims a refresh that did not happen.

The top-level `last_successful_refresh_utc` only moves forward when EVERY series
in the run succeeded. A partial run is recorded under `last_run` instead.

Tokens are read from environment variables (or a local .env file, never committed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sources import ADAPTERS, FetchError  # noqa: E402
from transforms import DERIVED_COLUMN, TRANSFORMS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "series.yaml"
DATA = ROOT / "data"
STATUS = DATA / "status.json"
LOG_FILE = ROOT / "verify" / "refresh_log.txt"
LOG_KEEP_RUNS = 30  # refresh_log.txt keeps only the most recent runs

# Metadata copied into status.json so the front end needs nothing but data/.
META_KEYS = [
    "name", "panel", "chart", "source_org", "source_series_id", "units", "frequency",
    "seasonal_adjustment", "transform", "plot", "display_divisor", "display_units",
    "transform_note", "sample_start", "stale_after_days", "source_url",
]

_log_lines: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    _log_lines.append(msg)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_dotenv(path: Path) -> None:
    """Minimal .env reader so local runs work without extra packages. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_config() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    defaults = cfg.get("defaults", {})
    ids = set()
    for s in cfg["series"]:
        for k, v in defaults.items():
            s.setdefault(k, v)
        if s["id"] in ids:
            raise SystemExit(f"duplicate series id in config: {s['id']}")
        ids.add(s["id"])
        if s["api"] not in ADAPTERS:
            raise SystemExit(f"{s['id']}: unknown api {s['api']!r}")
        if s["transform"] not in TRANSFORMS:
            raise SystemExit(f"{s['id']}: unknown transform {s['transform']!r}")
    return cfg


def load_status() -> dict:
    if STATUS.exists():
        return json.loads(STATUS.read_text(encoding="utf-8"))
    return {"last_successful_refresh_utc": None, "series": {}}


def write_atomic(path: Path, text: str) -> None:
    """Write to a temp file then rename, so a crash never leaves a half-written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def to_csv_text(df: pd.DataFrame) -> str:
    # Keep up to 6 decimals; source values are not altered beyond float formatting.
    return df.to_csv(index=False, date_format="%Y-%m-%d", float_format="%.6f")


def validate(s: dict, df: pd.DataFrame, old: pd.DataFrame | None) -> None:
    """Reject obviously broken responses instead of overwriting good data with them."""
    if df.empty:
        raise FetchError("source returned no observations")
    if df["date"].duplicated().any():
        raise FetchError("source returned duplicate dates")
    if old is not None and len(df) < 0.8 * len(old):
        raise FetchError(f"source returned {len(df)} rows vs {len(old)} previously stored; refusing to shrink history")


def diff_summary(old: pd.DataFrame | None, new: pd.DataFrame) -> str:
    if old is None:
        return f"new file, {len(new)} rows"
    old_dates = set(old["date"].astype(str))
    new_dates = set(new["date"].dt.strftime("%Y-%m-%d"))
    added = len(new_dates - old_dates)
    merged = new.assign(d=new["date"].dt.strftime("%Y-%m-%d")).merge(
        old.assign(d=old["date"].astype(str)), on="d", suffixes=("", "_old"))
    revised = int(((merged["value"] - merged["value_old"]).abs() > 1e-6).sum())
    if added == 0 and revised == 0:
        return "no new data"
    return f"{added} new obs, {revised} revised obs"


def refresh_series(s: dict, entry: dict, now: str) -> bool:
    """Fetch one series. Returns True on success. Mutates `entry` (its status.json record)."""
    path = DATA / f"{s['id']}.csv"
    old = pd.read_csv(path) if path.exists() else None
    entry["last_fetch_attempt_utc"] = now
    entry["meta"] = {k: s.get(k) for k in META_KEYS}
    try:
        df = ADAPTERS[s["api"]](s).sort_values("date").reset_index(drop=True)
        validate(s, df, old)
        df = TRANSFORMS[s["transform"]](df)
        change = diff_summary(old, df)
        write_atomic(path, to_csv_text(df))
    except Exception as exc:  # any failure: keep old data, record error, move on
        entry["status"] = "error"
        entry["error"] = f"{type(exc).__name__}: {exc}"[:500]
        # last_successful_fetch_utc and latest_observation_date are left untouched on purpose.
        kept = f"kept previous data (latest obs {entry.get('latest_observation_date')})" if old is not None else "no previous data"
        log(f"  [ERROR] {s['id']:<22} {entry['error']} -> {kept}")
        return False

    latest = df["date"].max()
    entry.update({
        "status": "ok",
        "error": None,
        "latest_observation_date": latest.strftime("%Y-%m-%d"),
        "latest_value": float(df.loc[df["date"] == latest, "value"].iloc[0]),
        "derived_column": DERIVED_COLUMN[s["transform"]],
        "n_obs": int(len(df)),
        "first_observation_date": df["date"].min().strftime("%Y-%m-%d"),
        "last_successful_fetch_utc": now,
    })
    age = (pd.Timestamp(now[:10]) - latest).days
    stale = " STALE(obs age %dd > %dd)" % (age, s["stale_after_days"]) if age > s["stale_after_days"] else ""
    log(f"  [OK]    {s['id']:<22} latest={entry['latest_observation_date']} n={len(df):<5} {change}{stale}")
    return True


def append_run_log() -> None:
    """Append this run to verify/refresh_log.txt, keeping only the last LOG_KEEP_RUNS runs."""
    LOG_FILE.parent.mkdir(exist_ok=True)
    sep = "=" * 78
    runs = LOG_FILE.read_text(encoding="utf-8").split(sep + "\n") if LOG_FILE.exists() else []
    runs = [r for r in runs if r.strip()] + ["\n".join(_log_lines) + "\n"]
    LOG_FILE.write_text("".join(sep + "\n" + r for r in runs[-LOG_KEEP_RUNS:]), encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated series ids to refresh")
    ap.add_argument("--no-log-file", action="store_true", help="do not append to verify/refresh_log.txt")
    args = ap.parse_args(argv)
    _log_lines.clear()  # main() may be called repeatedly from the Streamlit app

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    cfg = load_config()
    status = load_status()
    DATA.mkdir(exist_ok=True)

    selected = cfg["series"]
    if args.only:
        wanted = set(args.only.split(","))
        selected = [s for s in selected if s["id"] in wanted]

    started = utc_now()
    where = os.environ.get("REFRESH_WHERE") or (
        "GitHub Actions run %s" % os.environ["GITHUB_RUN_ID"] if os.environ.get("GITHUB_RUN_ID") else "local")
    log(f"Refresh started {started} ({where}); {len(selected)} series")

    ok = 0
    for s in selected:
        entry = status["series"].setdefault(s["id"], {})
        ok += refresh_series(s, entry, utc_now())

    # Keep config order (the front end draws series in this order) and drop removed series.
    status["series"] = {s["id"]: status["series"][s["id"]] for s in cfg["series"] if s["id"] in status["series"]}
    status["charts"] = cfg.get("charts", {})

    n_err = len(selected) - ok
    run_status = "ok" if n_err == 0 else ("failed" if ok == 0 else "partial")
    finished = utc_now()
    status["last_run"] = {
        "started_utc": started, "finished_utc": finished, "where": where,
        "status": run_status, "series_ok": ok, "series_error": n_err,
        "series_attempted": [s["id"] for s in selected],
    }
    # Whole-dashboard timestamp: only a full run (not --only) in which every series succeeded.
    full_run = len(selected) == len(cfg["series"])
    if full_run and n_err == 0:
        status["last_successful_refresh_utc"] = finished
    status["manual_panels"] = {
        "market_data": {
            "file": "data/manual/market_data.csv",
            "auto_refreshed": False,
            "note": "Broker survey data entered by hand; the scheduled refresh does NOT update it.",
        }
    }
    write_atomic(STATUS, json.dumps(status, indent=2, ensure_ascii=False) + "\n")

    log(f"Refresh finished {finished}: status={run_status}, ok={ok}, errors={n_err}; "
        f"last_successful_refresh_utc={status['last_successful_refresh_utc']}")
    log("Manual panel C (broker market data) was NOT refreshed (manual quarterly update).")
    if not args.no_log_file:
        append_run_log()
    if n_err and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::{n_err} series failed to refresh; previous data kept. See data/status.json.")
    # Exit 0 on partial failure so the workflow still publishes the good series.
    return 1 if run_status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
