"""
Source adapters: one function per API.

Each adapter takes a series config dict and returns a DataFrame with two
columns, `date` (datetime64, first day of the period for monthly data) and
`value` (float), sorted by date. Adapters raise an exception on any problem;
fetch.py decides what to do with it (keep the old data, record the error).

Tokens come from environment variables only (BANXICO_TOKEN, INEGI_TOKEN).
"""

from __future__ import annotations

import os
import time
from datetime import date

import pandas as pd
import requests

TIMEOUT = 90
HEADERS = {"User-Agent": "mexico-econ-dashboard/1.0 (python-requests)"}


class FetchError(RuntimeError):
    """Raised when a series cannot be fetched or fails validation."""


def _get(url: str, *, headers: dict | None = None, params: dict | None = None, tries: int = 3) -> requests.Response:
    """GET with a few retries and exponential backoff for transient errors."""
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(url, headers={**HEADERS, **(headers or {})}, params=params, timeout=TIMEOUT)
            if resp.status_code >= 500 or resp.status_code == 429:
                raise FetchError(f"HTTP {resp.status_code}")
            return resp
        except (requests.RequestException, FetchError) as exc:
            last_exc = exc
            if attempt < tries:
                time.sleep(2 ** attempt)
    raise FetchError(f"request failed after {tries} attempts: {last_exc}")


def _require_token(name: str) -> str:
    tok = os.environ.get(name, "").strip()
    if not tok:
        raise FetchError(f"environment variable {name} is not set")
    return tok


def _redact(text: str, secret: str) -> str:
    """Never let a token leak into logs or status.json."""
    return text.replace(secret, "***") if secret else text


# --------------------------------------------------------------------------
# Banco de México SIE API
# Docs: https://www.banxico.org.mx/SieAPIRest/service/v1/
# Response: {"bmx": {"series": [{"idSerie", "titulo", "datos": [{"fecha": "dd/mm/yyyy", "dato": "17.1234"}]}]}}
# Missing values are reported as "N/E".
# --------------------------------------------------------------------------
def fetch_banxico(cfg: dict) -> pd.DataFrame:
    token = _require_token("BANXICO_TOKEN")
    url = cfg["endpoint"].format(start=cfg["sample_start"], end=date.today().isoformat())
    resp = _get(url, headers={"Bmx-Token": token, "Accept": "application/json"})
    if resp.status_code != 200:
        raise FetchError(_redact(f"Banxico HTTP {resp.status_code}: {resp.text[:200]}", token))
    series = resp.json()["bmx"]["series"][0]
    if series.get("idSerie") != cfg["source_series_id"]:
        raise FetchError(f"Banxico returned series {series.get('idSerie')}, expected {cfg['source_series_id']}")
    rows = [
        (d["fecha"], d["dato"].replace(",", ""))
        for d in series.get("datos", [])
        if d.get("dato") not in (None, "", "N/E")
    ]
    df = pd.DataFrame(rows, columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"], format="%d/%m/%Y")
    df["value"] = df["value"].astype(float)
    return df


# --------------------------------------------------------------------------
# INEGI Banco de Indicadores API (BIE-BISE source, national area "00")
# Docs: https://www.inegi.org.mx/servicios/api_indicadores.html
# Response: {"Series": [{"INDICADOR", "FREQ", "UNIT", "OBSERVATIONS": [{"TIME_PERIOD": "2026/09", "OBS_VALUE": "106.84"}]}]}
# --------------------------------------------------------------------------
def _inegi_period(p: str) -> pd.Timestamp:
    """INEGI periods: 'YYYY/MM' (monthly), 'YYYY/QQ' is not used here, 'YYYY' (annual)."""
    parts = p.split("/")
    if len(parts) == 2:
        return pd.Timestamp(int(parts[0]), int(parts[1]), 1)
    if len(parts) == 1:
        return pd.Timestamp(int(parts[0]), 1, 1)
    raise FetchError(f"unrecognised INEGI period {p!r}")


def fetch_inegi(cfg: dict) -> pd.DataFrame:
    token = _require_token("INEGI_TOKEN")
    url = cfg["endpoint"].format(token=token)
    resp = _get(url)
    if resp.status_code != 200:
        raise FetchError(_redact(f"INEGI HTTP {resp.status_code}: {resp.text[:200]}", token))
    try:
        series = resp.json()["Series"][0]
    except (ValueError, KeyError, IndexError) as exc:
        raise FetchError(_redact(f"INEGI unexpected response: {resp.text[:200]}", token)) from exc
    if str(series.get("INDICADOR")) != str(cfg["source_series_id"]):
        raise FetchError(f"INEGI returned indicator {series.get('INDICADOR')}, expected {cfg['source_series_id']}")
    rows = [
        (_inegi_period(o["TIME_PERIOD"]), float(o["OBS_VALUE"]))
        for o in series.get("OBSERVATIONS", [])
        if o.get("OBS_VALUE") not in (None, "")
    ]
    df = pd.DataFrame(rows, columns=["date", "value"])
    return df[df["date"] >= pd.Timestamp(cfg["sample_start"])]


# --------------------------------------------------------------------------
# U.S. BTS Border Crossing Entry Data (Socrata SODA API, no token required)
# Dataset: https://data.bts.gov/Research-and-Statistics/Border-Crossing-Entry-Data/keg4-3bc2
# We let the server sum `value` by month for the requested filters
# (one port, or every port on the U.S.-Mexico border).
# --------------------------------------------------------------------------
def fetch_bts(cfg: dict) -> pd.DataFrame:
    # A list value means "sum these ports", e.g. port_name: [El Paso, Ysleta].
    filters = [
        f"{k} IN (" + ", ".join(f"'{x}'" for x in v) + ")" if isinstance(v, list) else f"{k}='{v}'"
        for k, v in cfg.get("params", {}).items()
    ]
    filters.append(f"date >= '{cfg['sample_start']}T00:00:00'")
    params = {
        "$select": "date, sum(value) AS value",
        "$where": " AND ".join(filters),
        "$group": "date",
        "$order": "date",
        "$limit": 50000,
    }
    app_token = os.environ.get("BTS_APP_TOKEN", "").strip()  # optional; raises rate limits
    resp = _get(cfg["endpoint"], params=params, headers={"X-App-Token": app_token} if app_token else None)
    if resp.status_code != 200:
        raise FetchError(f"BTS HTTP {resp.status_code}: {resp.text[:200]}")
    df = pd.DataFrame(resp.json())
    if df.empty:
        raise FetchError("BTS returned no rows (check params: port name, measure, border)")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df["value"] = df["value"].astype(float)
    return df[["date", "value"]]


ADAPTERS = {"banxico": fetch_banxico, "inegi": fetch_inegi, "bts": fetch_bts}
