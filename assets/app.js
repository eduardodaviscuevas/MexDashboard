/*
 * Mexico economy dashboard front end.
 * Reads ONLY data/status.json, data/<series>.csv and data/manual/market_data.csv.
 * All chart metadata (title, units, source link, notes) comes from status.json,
 * which src/fetch.py builds from config/series.yaml.
 */
"use strict";

// Validated categorical palette (fixed order, never cycled). Max 3 series per chart.
const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"];
const MX_TZ = "America/Mexico_City";
const DAY_MS = 86400000;

// ---------- helpers ----------
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "html") e.innerHTML = v; else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};

const fmtUTC = (iso) => new Date(iso).toISOString().replace("T", " ").slice(0, 16) + " UTC";
const fmtMX = (iso) => new Intl.DateTimeFormat("en-GB", {
  timeZone: MX_TZ, year: "numeric", month: "short", day: "2-digit",
  hour: "2-digit", minute: "2-digit", timeZoneName: "short",
}).format(new Date(iso)) + " (Mexico City)";

const parseDate = (s) => new Date(s + "T00:00:00Z");
const daysSince = (d) => Math.floor((Date.now() - d.getTime()) / DAY_MS);

function fmtPeriod(dateStr, freq) {
  const d = parseDate(dateStr);
  if (freq === "monthly") return d.toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
  return dateStr;
}

const fmtNum = (v, digits = 2) =>
  v == null || Number.isNaN(v) ? "n/a" : v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });

async function loadCSV(url) {
  const resp = await fetch(url, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${url}: HTTP ${resp.status}`);
  return Papa.parse(await resp.text(), { header: true, skipEmptyLines: true, dynamicTyping: false }).data;
}

// STALE if the last fetch failed, or the latest observation is older than the
// series' configured tolerance (period length + normal publication lag + grace).
function staleness(st) {
  const reasons = [];
  if (st.status !== "ok") reasons.push(`last fetch failed (${st.error || "unknown error"})`);
  if (st.latest_observation_date) {
    const age = daysSince(parseDate(st.latest_observation_date));
    if (age > st.meta.stale_after_days) reasons.push(`latest observation is ${age} days old (expected ≤ ${st.meta.stale_after_days})`);
  } else reasons.push("no data");
  return reasons;
}

// ---------- refresh box ----------
function renderRefreshBox(status) {
  const box = document.getElementById("refresh-box");
  const ok = status.last_successful_refresh_utc;
  const run = status.last_run || {};
  box.innerHTML = "";
  box.append(
    el("div", { class: "label" }, "Last successful refresh (all series fetched)"),
    el("div", { class: "ts" }, ok ? fmtUTC(ok) : "never"),
    el("div", {}, ok ? fmtMX(ok) : ""),
  );
  if (run.status && run.status !== "ok") {
    box.append(el("div", { class: "run-warning" },
      `Latest run ${fmtUTC(run.finished_utc)}: ${run.status.toUpperCase()}, ${run.series_error} series failed; their previous data is shown and marked STALE.`));
  } else if (run.finished_utc) {
    box.append(el("div", { class: "label", style: "margin-top:4px" }, `Latest run: ${run.status} · ${run.series_ok} series · ${run.where || ""}`));
  }
  box.append(el("div", { style: "font-size:.78rem;color:var(--text-muted);margin-top:4px" },
    "This is when data was fetched, not the date of the data. Each chart shows its own latest observation."));
}

// ---------- official-series charts (panels A and B) ----------
async function renderChart(chartId, chartCfg, members, container) {
  const card = el("div", { class: "card", id: `chart-${chartId}` });
  const titleEl = el("h3", {}, chartCfg.title || members[0].meta.name);
  card.append(titleEl);
  if (chartCfg.note) card.append(el("p", { class: "chart-note" }, chartCfg.note));
  const plotDiv = el("div", { class: "chart" });
  card.append(plotDiv);
  container.append(card);

  const traces = [];
  const shapes = [];
  const staleReasons = [];
  const latestLines = [];

  for (const [i, st] of members.entries()) {
    const m = st.meta;
    const rows = await loadCSV(`data/${st.id}.csv`);
    const col = m.plot === "derived" ? st.derived_column : "value";
    const div = m.display_divisor || 1;
    const pts = rows.filter((r) => r[col] !== "" && r[col] != null);
    const x = pts.map((r) => r.date);
    const y = pts.map((r) => parseFloat(r[col]) / div);
    const shape = chartCfg.shape || "line";
    const trace = {
      x, y, name: m.name, type: shape === "bar" ? "bar" : "scatter", mode: "lines",
      line: { color: SERIES_COLORS[i], width: 2, shape: shape === "step" ? "hv" : "linear" },
      marker: { color: SERIES_COLORS[i] },
      hovertemplate: `%{y:,.2f} ${m.display_units}<extra>${m.name}</extra>`,
    };
    traces.push(trace);

    const reasons = staleness(st);
    if (reasons.length) staleReasons.push(...reasons.map((r) => `${m.name}: ${r}`));
    const lastY = y.length ? y[y.length - 1] : null;
    latestLines.push(el("div", {},
      members.length > 1 ? el("span", { style: `color:${SERIES_COLORS[i]};font-weight:700` }, "■ ") : null,
      el("span", { class: "latest-obs" }, `${fmtPeriod(st.latest_observation_date, m.frequency)}`),
      ` — ${fmtNum(lastY)} ${members.length > 1 ? "(" + m.name + ")" : ""}`,
    ));
  }

  if (chartCfg.reference_line != null) {
    shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: chartCfg.reference_line, y1: chartCfg.reference_line,
      line: { color: "#77756f", width: 1, dash: "dash" } });
  }
  if (chartCfg.zero_line) {
    shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "#52514e", width: 1 } });
  }

  const m0 = members[0].meta;
  Plotly.newPlot(plotDiv, traces, {
    margin: { l: 56, r: 12, t: 8, b: 32 },
    paper_bgcolor: "#fcfcfb", plot_bgcolor: "#fcfcfb",
    font: { family: "system-ui, sans-serif", size: 12, color: "#52514e" },
    xaxis: { gridcolor: "#ecebe6", linecolor: "#c9c7c0" },
    yaxis: { title: { text: m0.display_units, font: { size: 11 } }, gridcolor: "#ecebe6", zeroline: false },
    hovermode: "x unified",
    showlegend: members.length > 1,
    legend: { orientation: "h", y: 1.12, x: 0 },
    shapes,
    annotations: chartCfg.reference_label ? [{ xref: "paper", x: 1, y: chartCfg.reference_line, text: chartCfg.reference_label,
      showarrow: false, xanchor: "right", yanchor: "bottom", font: { size: 10, color: "#77756f" } }] : [],
    bargap: 0.15,
  }, { displayModeBar: false, responsive: true });

  titleEl.append(staleReasons.length
    ? el("span", { class: "badge badge-stale", title: staleReasons.join("\n") }, "⚠ STALE")
    : el("span", { class: "badge badge-ok" }, "✓ current"));

  // Metadata block (one row per required field).
  const dl = el("dl", { class: "meta" });
  const add = (k, v) => dl.append(el("dt", {}, k), el("dd", {}, v));
  add("Latest observation", el("div", {}, latestLines));
  add("Units", m0.display_units + (m0.units && m0.units !== m0.display_units ? ` (source: ${m0.units})` : ""));
  add("Frequency", `${m0.frequency}${m0.seasonal_adjustment ? " · " + m0.seasonal_adjustment : ""}`);
  add("Transformation", members.length > 1 && members[1].meta.transform_note !== m0.transform_note
    ? el("div", {}, members.map((s) => el("div", {}, `${s.meta.name}: ${s.meta.transform_note}`)))
    : m0.transform_note);
  const srcs = [...new Map(members.map((s) => [s.meta.source_url + s.meta.source_series_id, s])).values()];
  add("Source", el("div", {}, srcs.map((s) => el("div", {},
    el("a", { href: s.meta.source_url, target: "_blank", rel: "noopener" }, s.meta.source_org),
    ` · series ${s.meta.source_series_id}`))));
  const fetched = members.map((s) => s.last_successful_fetch_utc).filter(Boolean).sort()[0];
  add("Last successful fetch", fetched ? fmtUTC(fetched) : "never");
  if (staleReasons.length) add("Why STALE", el("div", { class: "stale-reason" }, staleReasons.map((r) => el("div", {}, r))));
  card.append(dl);
}

async function renderOfficialPanels(status) {
  const byChart = new Map();
  for (const [id, st] of Object.entries(status.series)) {
    st.id = id;
    const key = st.meta.chart || id;
    if (!byChart.has(key)) byChart.set(key, []);
    byChart.get(key).push(st);
  }
  // Charts render in config order (status.charts preserves YAML order); orphans afterwards.
  const order = [...Object.keys(status.charts || {}), ...byChart.keys()].filter((k, i, a) => a.indexOf(k) === i);
  for (const key of order) {
    const members = byChart.get(key);
    if (!members) continue;
    const cfg = (status.charts || {})[key] || {};
    const panel = cfg.panel || members[0].meta.panel;
    try {
      await renderChart(key, cfg, members, document.getElementById(`charts-${panel}`));
    } catch (err) {
      document.getElementById(`charts-${panel}`).append(el("div", { class: "card" }, `Could not draw ${key}: ${err.message}`));
    }
  }
}

// ---------- Panel C: manual broker data ----------
function quarterEnd(q) { // "2026Q3" -> Date of last day of quarter
  const m = /^(\d{4})\s*-?Q([1-4])$/i.exec(q.trim());
  if (!m) return null;
  return new Date(Date.UTC(+m[1], +m[2] * 3, 0));
}

async function renderManualPanel() {
  const ageBox = document.getElementById("manual-age");
  const grid = document.getElementById("charts-C");
  let rows;
  try {
    rows = await loadCSV("data/manual/market_data.csv");
  } catch (err) {
    ageBox.textContent = "Could not load data/manual/market_data.csv: " + err.message;
    return;
  }
  const withData = rows.filter((r) => r.vacancy_rate_pct !== "" || r.asking_rent_usd_sqft_yr !== "");
  if (!withData.length) {
    ageBox.append(el("p", { class: "empty-note" }, "No broker values have been entered yet. See docs/UPDATING_MARKET_DATA.md."));
  } else {
    const pubDates = withData.map((r) => r.report_publication_date).filter(Boolean).sort();
    const latestPub = pubDates[pubDates.length - 1];
    const quarters = withData.map((r) => r.quarter).sort();
    const latestQ = quarters[quarters.length - 1];
    const qEnd = quarterEnd(latestQ);
    ageBox.append(
      "Latest data point: ", el("strong", {}, latestQ),
      qEnd ? ` (quarter ended ${qEnd.toISOString().slice(0, 10)}, ` : " (",
      el("strong", {}, qEnd ? `${daysSince(qEnd)} days ago` : "?"), "). ",
      ...(latestPub ? ["Most recent report publication date: ", el("strong", {}, latestPub), ` (${daysSince(parseDate(latestPub))} days ago). `] : []),
      "Reports: ", [...new Set(withData.map((r) => r.source_name))].join(", "), ".",
    );
    if (qEnd && daysSince(qEnd) > 200) ageBox.append(" ", el("span", { class: "badge badge-stale" }, "⚠ STALE: more than two quarters old"));
  }

  const markets = [...new Set(rows.map((r) => r.market))];
  const metrics = [
    { col: "vacancy_rate_pct", title: "Industrial vacancy rate by market", units: "% of inventory" },
    { col: "asking_rent_usd_sqft_yr", title: "Average industrial asking rent by market", units: "US$ per sq. ft. per year (as published)" },
  ];
  for (const mt of metrics) {
    const card = el("div", { class: "card" }, el("h3", {}, mt.title));
    const plotDiv = el("div", { class: "chart" });
    card.append(plotDiv);
    grid.append(card);
    const traces = markets.map((mk, i) => {
      const pts = rows.filter((r) => r.market === mk && r[mt.col] !== "").sort((a, b) => a.quarter.localeCompare(b.quarter));
      return {
        x: pts.map((r) => r.quarter), y: pts.map((r) => parseFloat(r[mt.col])), name: mk,
        type: "scatter", mode: "lines+markers",
        line: { color: SERIES_COLORS[i % 3], width: 2 }, marker: { size: 8, color: SERIES_COLORS[i % 3] },
        hovertemplate: `%{y:.2f}<extra>${mk}</extra>`,
      };
    });
    const units = mt.units || [...new Set(rows.map((r) => r.asking_rent_unit).filter(Boolean))].join(" / ") || "as published";
    const hasPts = traces.some((t) => t.x.length);
    if (!hasPts) plotDiv.replaceWith(el("p", { class: "empty-note" }, "No values entered yet for this metric."));
    else Plotly.newPlot(plotDiv, traces, {
      margin: { l: 56, r: 12, t: 8, b: 32 }, paper_bgcolor: "#fcfcfb", plot_bgcolor: "#fcfcfb",
      font: { family: "system-ui, sans-serif", size: 12, color: "#52514e" },
      xaxis: { type: "category", categoryorder: "category ascending", gridcolor: "#ecebe6" },
      yaxis: { title: { text: units, font: { size: 11 } }, gridcolor: "#ecebe6" },
      hovermode: "x unified", legend: { orientation: "h", y: 1.12, x: 0 },
    }, { displayModeBar: false, responsive: true });
    const dl = el("dl", { class: "meta" });
    dl.append(el("dt", {}, "Units"), el("dd", {}, units));
    dl.append(el("dt", {}, "Frequency"), el("dd", {}, "quarterly (manual entry)"));
    dl.append(el("dt", {}, "Source"), el("dd", {}, "See table below: each value links to the exact report page"));
    dl.append(el("dt", {}, "Transformation"), el("dd", {}, "None; values as printed in the broker report"));
    card.append(dl);
  }

  // Full table so every number is traceable to its report.
  const tbl = el("table", { class: "manual" });
  const cols = ["market", "quarter", "vacancy_rate_pct", "asking_rent_usd_sqft_yr", "source_name", "report_publication_date", "verification", "notes"];
  tbl.append(el("tr", {}, cols.map((c) => el("th", {}, c))));
  for (const r of rows) {
    tbl.append(el("tr", {}, cols.map((c) => {
      if (c === "source_name") return el("td", {}, r.source_url ? el("a", { href: r.source_url, target: "_blank", rel: "noopener" }, r.source_name) : r.source_name);
      if (c === "verification") return el("td", { class: r.verification === "verified" ? "" : "unverified" }, r.verification || "UNVERIFIED");
      return el("td", {}, r[c] === "" ? "—" : r[c]);
    })));
  }
  document.getElementById("manual-table").append(tbl);
}

// ---------- main ----------
(async function main() {
  let status;
  try {
    const resp = await fetch("data/status.json", { cache: "no-cache" });
    status = await resp.json();
  } catch (err) {
    document.getElementById("refresh-box").textContent = "Could not load data/status.json: " + err.message;
    return;
  }
  renderRefreshBox(status);
  await renderOfficialPanels(status);
  await renderManualPanel();
  document.body.dataset.ready = "1"; // used by the screenshot script
})();
