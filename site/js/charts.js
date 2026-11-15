import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.17/+esm";
import {
  METRICS, currentCity, setupCityNav, loadCity, fmt, fmtMetric, fmtInt, escapeHtml,
  describeCorrelation, showError, gap,
} from "./data.js?v=__VERSION__";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const ORD = [1, 2, 3, 4, 5].map((i) => css(`--ord-${i}`));

const PATH_METRICS = [
  ["walk_access_pct", "Step 1 · Park access"],
  ["park_acres_per_1k", "Step 1 · Park access"],
  ["facilities_per_1k_kids", "Step 1 · Park access"],
  ["est_participation", "Step 2 · Youth sports"],
  ["pros_per_100k", "Step 3 · Going pro"],
  ["pros_public_per_100k", "Step 3 · Going pro"],
];
const X_OPTIONS = ["facilities_per_1k_kids", "park_acres_per_1k", "walk_access_pct"];
const Y_OPTIONS = ["pros_per_100k", "pros_public_per_100k", "pros_recent_per_100k"];

let summary, nbs;

// ------------------------------------------------------------------ headline
function renderHeadline() {
  const g = summary.income_groups;
  const lo = g[0], hi = g[g.length - 1];
  const fac = gap(lo.facilities_per_1k_kids, hi.facilities_per_1k_kids);
  const acre = gap(lo.park_acres_per_1k, hi.park_acres_per_1k);
  const walkLo = Math.round(lo.walk_access_pct * 100), walkHi = Math.round(hi.walk_access_pct * 100);
  const hero = fac.dir === "same" ? "About the same" : `${fac.text}× ${fac.dir === "less" ? "fewer" : "more"}`;
  const acrePhrase = acre.dir === "same" ? "about the same amount of" : `${acre.text}× ${acre.dir}`;
  // Only draw the "not distance" conclusion when the data actually shows it.
  const gaps = [acre.dir === "less" && "park size", fac.dir === "less" && "sports facilities"].filter(Boolean);
  const notDistance = gaps.length > 0 && walkLo >= walkHi - 5;
  const partial = summary.partial_correlations.find((c) => c.x === "facilities_per_1k_kids" && c.y === "pros_per_100k");
  document.getElementById("headline-card").innerHTML = `
    <div class="stat-label">Kids in the lowest-income fifth of neighborhoods have</div>
    <div class="hero-figure">${hero}</div>
    <p style="font-size:1.1rem;max-width:62ch">park courts and fields per child than kids in the highest-income fifth
      (${fmt(lo.facilities_per_1k_kids, "dec1")} vs ${fmt(hi.facilities_per_1k_kids, "dec1")} per 1,000 kids), and
      ${acrePhrase} park land per resident (${fmt(lo.park_acres_per_1k, "dec1")} vs ${fmt(hi.park_acres_per_1k, "dec1")} acres per 1,000 people).
      ${walkLo}% of them live within a 10-minute walk of a park, compared with ${walkHi}% in the highest-income fifth.
      ${notDistance ? `<strong>The gap is in ${gaps.join(" and ")}, not distance.</strong>` : ""}</p>
    <div class="grid grid-3" style="margin-top:1rem">
      <div class="stat"><span class="stat-label">Est. kids in organized sports</span>
        <span class="stat-value">${fmt(lo.est_participation, "pct")} vs ${fmt(hi.est_participation, "pct")}</span>
        <span class="stat-note">lowest vs highest income group (estimate)</span></div>
      <div class="stat"><span class="stat-label">Park courts &amp; fields vs. pro athletes</span>
        <span class="stat-value">ρ = ${partial ? partial.rho.toFixed(2) : "–"}</span>
        <span class="stat-note">${partial ? `${describeCorrelation(partial.rho, partial.p).strength.toLowerCase()}, after accounting for income (${describeCorrelation(partial.rho, partial.p).sig})` : ""}</span></div>
      <div class="stat"><span class="stat-label">Pro athletes found</span>
        <span class="stat-value">${fmtInt(summary.totals.pros)}</span>
        <span class="stat-note">${fmtInt(summary.totals.pros_public)} from public high schools</span></div>
    </div>`;
}

// ------------------------------------------------------------------ small multiples (HTML bars)
function renderMultiples() {
  const g = summary.income_groups;
  const money = (v) => fmt(v, "money").replace(/,000$/, "K").replace(/,(\d)\d\d$/, ".$1K");
  document.getElementById("multiples").innerHTML = PATH_METRICS.map(([key, step]) => {
    const max = Math.max(...g.map((x) => x[key]));
    const rows = g.map((x) => `
      <div class="bar-row">
        <span class="bar-label">${escapeHtml(x.label)}</span>
        <span class="bar-track"><span class="bar-scale"><span class="bar" style="width:${(x[key] / max) * 100}%"></span></span>
          <span class="bar-value">${fmtMetric(key, x[key])}</span></span>
      </div>`).join("");
    const desc = g.map((x) => `${x.label}: ${fmtMetric(key, x[key])}`).join("; ");
    return `<figure class="card" style="margin:0">
      <div class="small muted">${step}</div>
      <h3>${escapeHtml(METRICS[key].short)}${METRICS[key].estimate ? " <span class='badge'>estimate</span>" : ""}</h3>
      <div class="bars" role="img" aria-label="${escapeHtml(METRICS[key].short)} by income group. ${escapeHtml(desc)}">${rows}</div>
    </figure>`;
  }).join("");

  document.getElementById("groups-table").innerHTML = `<table>
    <thead><tr><th>Income group</th><th class="n">Median income range</th><th class="n">Residents</th>
      ${PATH_METRICS.map(([k]) => `<th class="n">${escapeHtml(METRICS[k].short)}</th>`).join("")}</tr></thead>
    <tbody>${g.map((x) => `<tr><td>${escapeHtml(x.label)}</td><td class="n">${money(x.income_min)} – ${money(x.income_max)}</td>
      <td class="n">${fmtInt(x.pop)}</td>${PATH_METRICS.map(([k]) => `<td class="n">${fmtMetric(k, x[k])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

// ------------------------------------------------------------------ scatter (Observable Plot)
/** 0, 1, 2, 5, 10, 20, 50, … up to the data max: readable ticks for a compressed axis. */
function niceLogTicks(values) {
  const max = Math.max(...values);
  const ticks = [0];
  for (let p = 1; p <= max * 1.2; p *= 10) for (const m of [1, 2, 5]) if (p * m <= max * 1.2) ticks.push(p * m);
  return ticks;
}

function groupOf(income) {
  if (income === null) return null;
  const g = summary.income_groups;
  for (const x of g) if (income <= x.income_max) return x.label;
  return g[g.length - 1].label;
}

function renderScatter() {
  const xKey = document.getElementById("x-select").value;
  const yKey = document.getElementById("y-select").value;
  const labels = summary.income_groups.map((g) => g.label);
  const pts = nbs.filter((p) => p.pop >= summary.thresholds.min_pop_for_stats && p[xKey] !== null && p[yKey] !== null);
  const box = document.getElementById("scatter");
  const width = Math.min(1000, box.clientWidth || 900);
  const chart = Plot.plot({
    width, height: Math.round(Math.min(520, width * 0.6)),
    marginLeft: 56, marginBottom: 48,
    style: { background: "transparent", color: css("--text-2"), fontSize: "13px", fontFamily: css("--font") },
    x: { label: `${METRICS[xKey].short} →`, type: METRICS[xKey].skewed ? "symlog" : "linear",
      ticks: METRICS[xKey].skewed ? niceLogTicks(pts.map((d) => d[xKey])) : 6,
      tickFormat: METRICS[xKey].fmt === "pct" ? (d) => `${Math.round(d * 100)}%` : (d) => fmt(d, "int") },
    y: { label: `↑ ${METRICS[yKey].short}`, type: "symlog", ticks: niceLogTicks(pts.map((d) => d[yKey])), tickFormat: (d) => fmt(d, "int") },
    color: { domain: labels, range: ORD },
    marks: [
      Plot.gridX(METRICS[xKey].skewed ? niceLogTicks(pts.map((d) => d[xKey])) : { ticks: 6 }, { stroke: css("--grid"), strokeOpacity: 1 }),
      Plot.gridY(niceLogTicks(pts.map((d) => d[yKey])), { stroke: css("--grid"), strokeOpacity: 1 }),
      Plot.ruleY([0], { stroke: css("--axis") }),
      Plot.dot(pts, {
        x: xKey, y: yKey, fill: (d) => groupOf(d.median_income), r: 4.5,
        stroke: css("--surface"), strokeWidth: 1.5, fillOpacity: 0.9,
      }),
      Plot.tip(pts, Plot.pointer({
        x: xKey, y: yKey,
        title: (d) => `${d.name}\n${METRICS[xKey].short}: ${fmtMetric(xKey, d[xKey])}\n${METRICS[yKey].short}: ${fmtMetric(yKey, d[yKey])}\nMedian income: ${fmt(d.median_income, "money")}\nResidents: ${fmtInt(d.pop)}`,
        fill: css("--surface"), stroke: css("--axis"),
      })),
    ],
  });
  chart.setAttribute("role", "img");
  chart.setAttribute("aria-label", `Scatter plot of ${METRICS[xKey].short} against ${METRICS[yKey].short} for ${pts.length} neighborhoods, colored by income group.`);
  box.replaceChildren(chart);

  document.getElementById("scatter-legend").innerHTML = labels.map((l, i) =>
    `<span><span class="swatch-dot" style="background:${ORD[i]}" aria-hidden="true"></span>${escapeHtml(l)} income</span>`).join("");

  const c = summary.correlations.find((r) => r.x === xKey && r.y === yKey);
  const pc = summary.partial_correlations.find((r) => r.x === xKey && r.y === yKey);
  const el = document.getElementById("scatter-reading");
  if (!c) { el.textContent = ""; return; }
  const d = describeCorrelation(c.rho, c.p);
  let text = `<strong>${d.strength}</strong> (ρ = ${c.rho.toFixed(2)}, ${d.sig}).`;
  if (pc) {
    const dp = describeCorrelation(pc.rho, pc.p);
    text += ` After accounting for neighborhood income: ${dp.strength.toLowerCase()} (ρ = ${pc.rho.toFixed(2)}, ${dp.sig}).`;
  }
  if (METRICS[xKey].skewed) text += ` <span class="muted small">The horizontal axis is compressed (log-like) so a few very park-rich neighborhoods don't squeeze everyone else into a corner.</span>`;
  el.innerHTML = text;
}

// ------------------------------------------------------------------ correlation list
function renderCorrelations() {
  const all = [
    ...summary.correlations.map((c) => ({ ...c, partial: false })),
    ...summary.partial_correlations.map((c) => ({ ...c, partial: true })),
  ].filter((c) => c.x !== "est_participation"); // participation is modeled from income: not an independent finding
  all.sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho));
  document.getElementById("corr-list").innerHTML = all.map((c) => {
    const d = describeCorrelation(c.rho, c.p);
    return `<li><span class="corr-strength">${d.strength}</span> between <em>${escapeHtml(METRICS[c.x].short.toLowerCase())}</em>
      and <em>${escapeHtml(METRICS[c.y].short.toLowerCase())}</em>${c.partial ? " <span class='badge'>after accounting for income</span>" : ""}
      <div class="small muted">ρ = ${c.rho.toFixed(2)} · ${d.sig} · ${c.n} neighborhoods</div></li>`;
  }).join("");
}

// ------------------------------------------------------------------ init
async function init() {
  const { city, cities } = await currentCity();
  setupCityNav(cities, city.slug);
  const data = await loadCity(city.slug);
  summary = data.summary;
  nbs = data.neighborhoods.features.map((f) => f.properties);

  document.title = `${summary.city.short_name} analysis · Park Access to Pro Sports`;
  document.getElementById("title").textContent = `${summary.city.name}: what the data shows`;
  document.getElementById("lede").textContent = `${fmtInt(summary.totals.neighborhoods)} neighborhoods, ${fmtInt(summary.totals.pop)} residents, ${fmtInt(summary.totals.parks)} public parks, and ${fmtInt(summary.totals.pros)} pro athletes traced to local high schools.`;
  document.getElementById("min-pop").textContent = fmtInt(summary.thresholds.min_pop_for_stats);
  document.getElementById("footer").innerHTML = `Data built ${summary.built} · ACS ${summary.acs_year - 4}–${summary.acs_year} · <a href="methodology.html?city=${encodeURIComponent(city.slug)}">Sources &amp; methodology</a>`;

  for (const [id, opts] of [["x-select", X_OPTIONS], ["y-select", Y_OPTIONS]]) {
    const sel = document.getElementById(id);
    sel.innerHTML = opts.map((k) => `<option value="${k}">${escapeHtml(METRICS[k].short)}</option>`).join("");
    sel.addEventListener("change", renderScatter);
  }
  renderHeadline();
  renderMultiples();
  renderScatter();
  renderCorrelations();
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderScatter, 150); });
}

init().catch((err) => showError(document.getElementById("main"), err));
