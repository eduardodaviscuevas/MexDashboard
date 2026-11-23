"""
Mexico economy monitor: Streamlit version.

    streamlit run streamlit_app.py

The app refreshes its own data: if the last refresh run is older than REFRESH_EVERY_HOURS,
the first visitor triggers src/fetch.py (Banxico, INEGI, BTS). fetch.py's rules still apply:
a series that fails keeps its previous data, is marked "error" and shows a STALE badge, and
the "last successful refresh" time only moves when every series succeeded.

Tokens: Streamlit Cloud secrets (BANXICO_TOKEN, INEGI_TOKEN) or a local .env file.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATUS = DATA / "status.json"
MANUAL = DATA / "manual" / "market_data.csv"
sys.path.insert(0, str(ROOT / "src"))
import fetch  # noqa: E402

REFRESH_EVERY_HOURS = 12
MX_TZ = ZoneInfo("America/Mexico_City")
COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]  # validated categorical palette, fixed order, max 3 per chart
STALE_RED = "#d03b3b"

st.set_page_config(page_title="Mexico economy monitor", page_icon="📈", layout="wide")


# ----------------------------------------------------------------------------- refresh
def load_secrets_into_env() -> None:
    """Streamlit Cloud secrets -> environment variables that src/sources.py reads."""
    try:
        for key in ("BANXICO_TOKEN", "INEGI_TOKEN", "BTS_APP_TOKEN"):
            if key in st.secrets and not os.environ.get(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass  # no secrets file locally: fetch.py falls back to .env


@st.cache_resource
def refresh_lock() -> threading.Lock:
    return threading.Lock()  # shared by all sessions so only one refresh runs at a time


def read_status() -> dict:
    return json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {"series": {}}


def parse_utc(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def hours_since_last_run(status: dict) -> float:
    last = parse_utc((status.get("last_run") or {}).get("finished_utc"))
    return float("inf") if last is None else (datetime.now(timezone.utc) - last).total_seconds() / 3600


def run_refresh(force: bool = False) -> list[str] | None:
    """Run fetch.py in-process. Returns the log lines, or None if no refresh was needed."""
    with refresh_lock():
        # Re-check inside the lock: another visitor may have just refreshed.
        if not force and hours_since_last_run(read_status()) < REFRESH_EVERY_HOURS:
            return None
        os.environ["REFRESH_WHERE"] = "Streamlit app"
        fetch.main([])
        return list(fetch._log_lines)


# ----------------------------------------------------------------------------- helpers
def fmt_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def fmt_mx(dt: datetime) -> str:
    local = dt.astimezone(MX_TZ)
    return local.strftime("%d %b %Y, %H:%M ") + (local.tzname() or "") + " (Mexico City)"


def fmt_period(date_str: str | None, freq: str) -> str:
    if not date_str:
        return "n/a"
    return pd.Timestamp(date_str).strftime("%b %Y") if freq == "monthly" else date_str


def badge(text: str, bg: str, fg: str = "#fff") -> str:
    return (f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:4px;'
            f'font-size:0.75rem;font-weight:700;vertical-align:middle;white-space:nowrap">{text}</span>')


def stale_reasons(st_entry: dict) -> list[str]:
    """STALE if the last fetch failed or the latest observation is older than allowed for this series."""
    reasons = []
    if st_entry.get("status") != "ok":
        reasons.append(f"last fetch failed ({st_entry.get('error') or 'unknown error'})")
    latest = st_entry.get("latest_observation_date")
    if latest:
        age = (datetime.now(timezone.utc).date() - pd.Timestamp(latest).date()).days
        limit = st_entry["meta"]["stale_after_days"]
        if age > limit:
            reasons.append(f"latest observation is {age} days old (expected ≤ {limit})")
    else:
        reasons.append("no data")
    return reasons


@st.cache_data(show_spinner=False)
def load_series_csv(series_id: str, mtime: float) -> pd.DataFrame:  # mtime busts the cache after a refresh
    return pd.read_csv(DATA / f"{series_id}.csv", parse_dates=["date"])


def base_layout(y_title: str, legend: bool) -> dict:
    return dict(
        height=320, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
        font=dict(family="system-ui, sans-serif", size=12, color="#52514e"),
        xaxis=dict(gridcolor="#ecebe6"), yaxis=dict(title=dict(text=y_title, font=dict(size=11)), gridcolor="#ecebe6"),
        hovermode="x unified", showlegend=legend, legend=dict(orientation="h", y=1.12, x=0),
    )


# ----------------------------------------------------------------------------- panels A and B
def render_chart(chart_cfg: dict, members: list[dict]) -> None:
    m0 = members[0]["meta"]
    shape = chart_cfg.get("shape", "line")
    fig = go.Figure()
    latest_lines, reasons = [], []
    for i, s in enumerate(members):
        m = s["meta"]
        path = DATA / f"{s['id']}.csv"
        if not path.exists():
            reasons.append(f"{m['name']}: no data file")
            continue
        df = load_series_csv(s["id"], path.stat().st_mtime)
        col = s.get("derived_column") if m["plot"] == "derived" else "value"
        df = df.dropna(subset=[col])
        y = df[col] / (m.get("display_divisor") or 1)
        hover = f"%{{y:,.2f}} {m['display_units']}<extra>{m['name']}</extra>"
        if shape == "bar":
            fig.add_bar(x=df["date"], y=y, name=m["name"], marker_color=COLORS[i], hovertemplate=hover)
        else:
            fig.add_scatter(x=df["date"], y=y, name=m["name"], mode="lines", hovertemplate=hover,
                            line=dict(color=COLORS[i], width=2, shape="hv" if shape == "step" else "linear"))
        last_val = f"{y.iloc[-1]:,.2f}" if len(y) else "n/a"
        prefix = f"<span style='color:{COLORS[i]}'>■</span> " if len(members) > 1 else ""
        suffix = f" ({m['name']})" if len(members) > 1 else ""
        latest_lines.append(f"{prefix}<b>{fmt_period(s.get('latest_observation_date'), m['frequency'])}</b> — {last_val}{suffix}")
        reasons += [f"{m['name']}: {r}" for r in stale_reasons(s)]

    if chart_cfg.get("zero_line"):
        fig.add_hline(y=0, line_color="#52514e", line_width=1)
    if chart_cfg.get("reference_line") is not None:
        fig.add_hline(y=chart_cfg["reference_line"], line_dash="dash", line_color="#77756f", line_width=1,
                      annotation_text=chart_cfg.get("reference_label", ""), annotation_position="top right")
    fig.update_layout(**base_layout(m0["display_units"], legend=len(members) > 1), bargap=0.15)

    with st.container(border=True):
        status_badge = badge("⚠ STALE", STALE_RED) if reasons else badge("✓ current", "#e5efe5", "#1d4d1d")
        st.markdown(f"#### {chart_cfg.get('title') or m0['name']} &nbsp;{status_badge}", unsafe_allow_html=True)
        if chart_cfg.get("note"):
            st.markdown(f"**{chart_cfg['note']}**")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

        units = m0["display_units"] + (f" (source: {m0['units']})" if m0["units"] != m0["display_units"] else "")
        notes = {s["meta"]["transform_note"] for s in members}
        transform = m0["transform_note"] if len(notes) == 1 else "<br>".join(
            f"{s['meta']['name']}: {s['meta']['transform_note']}" for s in members)
        seen, sources = set(), []
        for s in members:
            key = (s["meta"]["source_url"], s["meta"]["source_series_id"])
            if key not in seen:
                seen.add(key)
                sources.append(f"<a href='{s['meta']['source_url']}' target='_blank'>{s['meta']['source_org']}</a>"
                               f" · series <code>{s['meta']['source_series_id']}</code>")
        fetched = sorted(filter(None, (s.get("last_successful_fetch_utc") for s in members)))
        rows = [
            ("Latest observation", "<br>".join(latest_lines)),
            ("Units", units),
            ("Frequency", f"{m0['frequency']} · {m0.get('seasonal_adjustment', '')}"),
            ("Transformation", transform),
            ("Source", "<br>".join(sources)),
            ("Last successful fetch", fmt_utc(parse_utc(fetched[0])) if fetched else "never"),
        ]
        if reasons:
            rows.append(("Why STALE", f"<span style='color:{STALE_RED};font-weight:600'>" + "<br>".join(reasons) + "</span>"))
        st.markdown(
            "<table style='font-size:0.82rem;border:none'>" + "".join(
                f"<tr><td style='font-weight:600;vertical-align:top;padding:1px 10px 1px 0;border:none;white-space:nowrap'>{k}</td>"
                f"<td style='padding:1px 0;border:none'>{v}</td></tr>" for k, v in rows) + "</table>",
            unsafe_allow_html=True)


def render_official_panel(panel: str, status: dict) -> None:
    by_chart: dict[str, list[dict]] = {}
    for sid, s in status.get("series", {}).items():
        s["id"] = sid
        if s.get("meta", {}).get("panel") == panel:
            by_chart.setdefault(s["meta"].get("chart") or sid, []).append(s)
    charts = status.get("charts", {})
    keys = [k for k in charts if k in by_chart] + [k for k in by_chart if k not in charts]
    cols = st.columns(2)
    for i, key in enumerate(keys):
        with cols[i % 2]:
            render_chart(charts.get(key, {}), by_chart[key])


# ----------------------------------------------------------------------------- panel C
def render_manual_panel() -> None:
    st.warning("**Non-official, broker survey, manually updated.** These figures are typed in by hand from public "
               "broker reports (one broker: CBRE Research). The automatic refresh does **not** touch them.", icon="✍️")
    if not MANUAL.exists():
        st.error("data/manual/market_data.csv not found")
        return
    df = pd.read_csv(MANUAL, dtype=str).fillna("")
    for c in ("vacancy_rate_pct", "asking_rent_usd_sqft_yr"):
        df[c + "_num"] = pd.to_numeric(df[c], errors="coerce")
    has = df[df["vacancy_rate_pct_num"].notna() | df["asking_rent_usd_sqft_yr_num"].notna()]
    if has.empty:
        st.info("No broker values entered yet. See docs/UPDATING_MARKET_DATA.md.")
    else:
        latest_q = has["quarter"].max()
        year, q = int(latest_q[:4]), int(latest_q[-1])
        q_end = (pd.Timestamp(year=year, month=q * 3, day=1) + pd.offsets.MonthEnd(0)).date()
        age = (datetime.now(timezone.utc).date() - q_end).days
        pubs = sorted(d for d in has["report_publication_date"] if d)
        line = f"Latest data point: **{latest_q}** (quarter ended {q_end}, **{age} days ago**)."
        if pubs:
            pub_age = (datetime.now(timezone.utc).date() - pd.Timestamp(pubs[-1]).date()).days
            line += f" Most recent report publication date: **{pubs[-1]}** ({pub_age} days ago)."
        if age > 200:
            line += " " + badge("⚠ STALE: more than two quarters old", STALE_RED)
        st.markdown(line, unsafe_allow_html=True)

    cols = st.columns(2)
    metrics = [("vacancy_rate_pct", "Industrial vacancy rate by market", "% of inventory"),
               ("asking_rent_usd_sqft_yr", "Average industrial asking rent by market", "US$ per sq. ft. per year (as published)")]
    for (col, title, units), slot in zip(metrics, cols):
        with slot, st.container(border=True):
            st.markdown(f"#### {title}")
            fig = go.Figure()
            for i, market in enumerate(df["market"].unique()):
                pts = df[(df["market"] == market) & df[col + "_num"].notna()].sort_values("quarter")
                if len(pts):
                    fig.add_scatter(x=pts["quarter"], y=pts[col + "_num"], name=market, mode="lines+markers",
                                    line=dict(color=COLORS[i % 3], width=2), marker=dict(size=9, color=COLORS[i % 3]),
                                    hovertemplate=f"%{{y:.2f}}<extra>{market}</extra>")
            if not fig.data:
                st.caption("No values entered yet for this metric.")
                continue
            layout = base_layout(units, legend=True)
            layout["xaxis"].update(type="category", categoryorder="category ascending")
            fig.update_layout(**layout)
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            st.caption(f"Units: {units} · Frequency: quarterly (manual entry) · Transformation: none, values as "
                       "printed in the report · Source: see table below (each row links to its report)")

    show = df[["market", "quarter", "vacancy_rate_pct", "asking_rent_usd_sqft_yr", "source_name", "source_url",
               "report_publication_date", "verification", "notes"]]
    st.dataframe(show, hide_index=True, width="stretch",
                 column_config={"source_url": st.column_config.LinkColumn("source_url", display_text="report link")})


# ----------------------------------------------------------------------------- page
def main() -> None:
    load_secrets_into_env()

    with st.sidebar:
        st.header("Data refresh")
        st.caption(f"Data refreshes automatically when the last run is more than {REFRESH_EVERY_HOURS} hours old.")
        force = st.button("Refresh now", width="stretch")

    status = read_status()
    log = None
    if force or hours_since_last_run(status) >= REFRESH_EVERY_HOURS:
        with st.spinner("Fetching the latest data from Banxico, INEGI and BTS (about 30–60 seconds)…"):
            try:
                log = run_refresh(force=force)
            except Exception as exc:  # never break the page; previous data is still shown
                st.error(f"Refresh crashed: {exc}. Showing previously saved data.")
        status = read_status()

    st.title("Mexico economy monitor")
    st.markdown("*Is Mexico's industrial / nearshoring story holding up under peso and interest-rate pressure?*")

    ok_ts = parse_utc(status.get("last_successful_refresh_utc"))
    run = status.get("last_run") or {}
    with st.container(border=True):
        c1, c2 = st.columns([2, 3])
        with c1:
            st.caption("LAST SUCCESSFUL REFRESH (ALL SERIES FETCHED)")
            st.markdown(f"### {fmt_utc(ok_ts) if ok_ts else 'never'}")
            st.markdown(fmt_mx(ok_ts) if ok_ts else "")
        with c2:
            if run.get("status") and run["status"] != "ok":
                st.error(f"Latest run {fmt_utc(parse_utc(run['finished_utc']))}: **{run['status'].upper()}**, "
                         f"{run['series_error']} series failed. Their previous data is shown and marked STALE.")
            elif run:
                st.success(f"Latest run {fmt_utc(parse_utc(run['finished_utc']))}: ok, {run['series_ok']} series "
                           f"({run.get('where', '')}).")
            st.caption("This is when the data was fetched, not the date of the data. Each chart shows its own "
                       "**latest observation** date.")

    with st.sidebar:
        if log:
            with st.expander("Log of the refresh just run", expanded=False):
                st.code("\n".join(log), language=None)
        st.markdown("---")
        st.markdown("Sources: Banco de México SIE API · INEGI BIE API · U.S. BTS Border Crossing Entry Data. "
                    "Panel C: CBRE Research, entered by hand.")

    st.header("A. Core macro indicators")
    st.caption("Official sources · refreshed automatically")
    render_official_panel("A", status)

    st.divider()
    st.header("B. Industrial real estate: demand and supply proxies")
    st.caption("Official sources · refreshed automatically")
    render_official_panel("B", status)

    st.divider()
    st.header("C. Market data (broker reports, manual quarterly update)")
    render_manual_panel()


main()
