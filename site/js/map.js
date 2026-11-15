import {
  METRICS, STEPS, currentCity, setupCityNav, loadCity, loadParks, fmt, fmtMetric, fmtInt,
  median, escapeHtml, showError,
} from "./data.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
const RAMP = [1, 2, 3, 4, 5].map((i) => css(`--seq-${i}`));
const MAP_LAYERS = [
  "median_income", "walk_access_pct", "park_acres_per_1k", "facilities_per_1k_kids",
  "est_participation", "pros_per_100k", "pros_public_per_100k", "pros_recent_per_100k",
];

const state = { metric: "facilities_per_1k_kids", selected: null, sortKey: "name", sortDir: 1 };
let data, features, map, geoLayer, athleteLayer, parkLayer, medians;

// ------------------------------------------------------------------ class breaks
function computeBreaks(values) {
  const v = values.filter((x) => x !== null && !Number.isNaN(x)).sort((a, b) => a - b);
  const q = (arr, p) => arr[Math.min(arr.length - 1, Math.floor(p * arr.length))];
  const zeros = v.filter((x) => x === 0).length / v.length;
  if (zeros >= 0.15) {
    // Many zeros (e.g. pro athletes): zero gets its own class, quantiles for the rest.
    const pos = v.filter((x) => x > 0);
    return { zeroClass: true, cuts: [0, q(pos, 0.25), q(pos, 0.5), q(pos, 0.75)] };
  }
  return { zeroClass: false, cuts: [q(v, 0.2), q(v, 0.4), q(v, 0.6), q(v, 0.8)] };
}
function classOf(value, br) {
  if (value === null || value === undefined) return -1;
  if (br.zeroClass) {
    if (value === 0) return 0;
    let i = 1;
    for (const c of br.cuts.slice(1)) if (value > c) i++;
    return Math.min(i, 4);
  }
  let i = 0;
  for (const c of br.cuts) if (value > c) i++;
  return i;
}
function legendLabels(br, key) {
  const f = (v) => fmtMetric(key, v);
  const c = br.cuts;
  if (br.zeroClass) return ["None", `Up to ${f(c[1])}`, `${f(c[1])} – ${f(c[2])}`, `${f(c[2])} – ${f(c[3])}`, `More than ${f(c[3])}`];
  return [`Up to ${f(c[0])}`, `${f(c[0])} – ${f(c[1])}`, `${f(c[1])} – ${f(c[2])}`, `${f(c[2])} – ${f(c[3])}`, `More than ${f(c[3])}`];
}

// ------------------------------------------------------------------ map styling
let breaks;
function styleFor(feature) {
  const p = feature.properties;
  const cls = classOf(p[state.metric], breaks);
  const unreliable = METRICS[state.metric].rate && !p.reliable;
  const selected = state.selected === p.nid;
  return {
    fillColor: cls < 0 ? css("--nodata") : RAMP[cls],
    fillOpacity: unreliable ? 0.35 : 0.78,
    color: selected ? css("--text") : css("--surface"),
    weight: selected ? 3 : 0.8,
    opacity: 1,
  };
}

function renderLegend() {
  const key = state.metric;
  breaks = computeBreaks(features.map((f) => f.properties[key]));
  const labels = legendLabels(breaks, key);
  document.getElementById("legend-title").textContent = METRICS[key].short;
  document.getElementById("legend").innerHTML = labels.map((l, i) =>
    `<div class="legend-row"><span class="legend-swatch" style="background:${RAMP[i]}"></span>${escapeHtml(l)}</div>`).join("")
    + `<div class="legend-row"><span class="legend-swatch nodata"></span>No data</div>`;
  const notes = [];
  notes.push("Each color holds about the same number of neighborhoods.");
  if (METRICS[key].rate) notes.push(`Faded areas have fewer than ${fmtInt(data.summary.thresholds.min_pop_reliable)} residents, so their rates swing a lot with one or two athletes.`);
  if (METRICS[key].estimate) notes.push("Estimated from household income: see Methodology.");
  document.getElementById("legend-note").textContent = notes.join(" ");
}

function restyle() {
  renderLegend();
  geoLayer.setStyle(styleFor);
  if (state.selected !== null) {
    geoLayer.eachLayer((l) => { if (l.feature.properties.nid === state.selected) l.bringToFront(); });
  }
  if (!document.getElementById("table-view").hidden) renderTable();
}

// ------------------------------------------------------------------ detail panel
function meterRow(key, p) {
  const v = p[key];
  const m = medians[key];
  const all = features.map((f) => f.properties[key]).filter((x) => x !== null).sort((a, b) => a - b);
  const max = all[Math.floor(all.length * 0.95)] || 1;   // cap at the 95th percentile so outliers don't flatten everyone else
  const w = v === null ? 0 : Math.min(100, (v / max) * 100);
  const mw = m === null ? 0 : Math.min(100, (m / max) * 100);
  let cmp = "";
  if (v !== null && m) {
    const ratio = v / m;
    cmp = ratio >= 1.15 ? `${ratio.toFixed(1)}× the typical neighborhood` : ratio <= 0.87 ? `${(ratio * 100).toFixed(0)}% of the typical neighborhood` : "About typical";
    if (m === 0) cmp = "";
    if (v === 0 && m > 0) cmp = "None here";
  }
  return `<div class="metric-row">
    <div class="metric-head"><span class="metric-name">${escapeHtml(METRICS[key].short)}${METRICS[key].estimate ? " <span class='badge'>estimate</span>" : ""}</span>
      <span class="metric-val">${fmtMetric(key, v)}</span></div>
    <div class="meter" role="img" aria-label="${escapeHtml(METRICS[key].short)}: ${fmtMetric(key, v)}; median neighborhood ${fmtMetric(key, m)}">
      <div class="meter-fill" style="width:${w}%"></div><div class="meter-median" style="left:${mw}%" title="Typical (median) neighborhood"></div></div>
    <div class="metric-compare">${cmp}${cmp ? " · " : ""}median ${fmtMetric(key, m)}</div>
  </div>`;
}

function renderDetail(nid) {
  const f = features.find((x) => x.properties.nid === nid);
  const el = document.getElementById("detail");
  if (!f) return;
  const p = f.properties;
  const group = (step) => Object.keys(METRICS).filter((k) => METRICS[k].step === step);
  const ath = data.athletes.filter((a) => a.nid === nid).sort((a, b) => (b.birth_year ?? 0) - (a.birth_year ?? 0));
  const athItems = ath.slice(0, 15).map((a) => `<li>${a.url ? `<a href="${escapeHtml(a.url)}" target="_blank" rel="noopener">${escapeHtml(a.name)}</a>` : escapeHtml(a.name)}
      <div class="meta">${escapeHtml(a.leagues.join(", "))}${a.birth_year ? ` · born ${a.birth_year}` : ""} · ${escapeHtml(a.school)} (${a.school_type})</div></li>`).join("");
  el.innerHTML = `
    <h2>${escapeHtml(p.name)}</h2>
    <p class="small muted">${fmtInt(p.pop)} residents · ${fmtInt(p.kids0_17)} kids under 18
      ${p.reliable ? "" : `<br><span class="badge">Small population: per-capita athlete rates are unreliable</span>`}</p>
    ${["income", "access", "participation", "pros"].map((s) => `
      <div class="step-header">${STEPS[s]}</div>
      <div class="path-v">${group(s).map((k) => meterRow(k, p)).join("")}</div>`).join("")}
    <div class="step-header">Pro athletes from high schools here (${ath.length})</div>
    ${ath.length ? `<ul class="athlete-list">${athItems}</ul>${ath.length > 15 ? `<p class="small muted">…and ${ath.length - 15} more</p>` : ""}`
      : `<p class="small muted">None found in Wikidata. That can mean none exist, or that their high school isn't recorded.</p>`}
    <p class="small muted" style="margin-top:1rem">The bar shows this neighborhood; the dark tick marks the typical neighborhood.</p>`;
}

function select(nid, { pan = false } = {}) {
  state.selected = nid;
  geoLayer.setStyle(styleFor);
  let target;
  geoLayer.eachLayer((l) => { if (l.feature.properties.nid === nid) { l.bringToFront(); target = l; } });
  if (pan && target) map.fitBounds(target.getBounds(), { maxZoom: 13, padding: [20, 20] });
  renderDetail(nid);
  history.replaceState(null, "", `${location.search}#n=${nid}`);
}

// ------------------------------------------------------------------ athletes & parks overlays
function renderAthletes() {
  if (athleteLayer) athleteLayer.remove();
  if (!document.getElementById("toggle-athletes").checked) return;
  const filter = document.getElementById("athlete-filter").value;
  const yr = data.summary.thresholds.recent_birth_year;
  const list = data.athletes.filter((a) => filter === "all" || (filter === "public" ? a.school_type === "public" : (a.birth_year ?? 0) >= yr));
  // One marker per school, sized by how many athletes it produced.
  const bySchool = new Map();
  for (const a of list) {
    const k = `${a.lat},${a.lon}`;
    if (!bySchool.has(k)) bySchool.set(k, { lat: a.lat, lon: a.lon, school: a.school, type: a.school_type, people: [] });
    bySchool.get(k).people.push(a);
  }
  athleteLayer = L.layerGroup(
    [...bySchool.values()].map((s) => L.circleMarker([s.lat, s.lon], {
      radius: 4 + Math.sqrt(s.people.length) * 1.6,
      fillColor: css("--athlete"), fillOpacity: 0.9, color: css("--surface"), weight: 2,
    }).bindTooltip(`<strong>${escapeHtml(s.school)}</strong> <span class="muted">(${s.type})</span><br>${s.people.length} pro athlete${s.people.length > 1 ? "s" : ""}: ${escapeHtml(s.people.slice(0, 4).map((p) => p.name).join(", "))}${s.people.length > 4 ? "…" : ""}`)),
  ).addTo(map);
}

async function toggleParks() {
  const on = document.getElementById("toggle-parks").checked;
  if (!on) { parkLayer?.remove(); return; }
  if (!parkLayer) {
    const parks = await loadParks(data.parksUrl);
    parkLayer = L.geoJSON(parks, {
      style: { color: css("--park"), weight: 1, fillColor: css("--park"), fillOpacity: 0.35 },
      onEachFeature: (f, l) => l.bindTooltip(`${escapeHtml(f.properties.name)}${f.properties.acres ? ` · ${fmt(f.properties.acres, "dec1")} acres` : ""}`, { sticky: true }),
    });
  }
  parkLayer.addTo(map);
  athleteLayer?.eachLayer((l) => l.bringToFront());
}

// ------------------------------------------------------------------ table view
const TABLE_COLS = ["name", "pop", "median_income", "walk_access_pct", "park_acres_per_1k", "facilities_per_1k_kids", "est_participation", "pros", "pros_per_100k"];
const COL_LABEL = { name: "Neighborhood", pop: "Residents", pros: "Pro athletes" };
function renderTable() {
  const rows = features.map((f) => f.properties).slice().sort((a, b) => {
    const x = a[state.sortKey], y = b[state.sortKey];
    if (x === null) return 1; if (y === null) return -1;
    return (typeof x === "string" ? x.localeCompare(y) : x - y) * state.sortDir;
  });
  const head = TABLE_COLS.map((k) => {
    const sorted = state.sortKey === k ? (state.sortDir === 1 ? "ascending" : "descending") : "none";
    return `<th class="${k === "name" ? "" : "n"}" aria-sort="${sorted}"><button data-sort="${k}">${escapeHtml(COL_LABEL[k] ?? METRICS[k].short)}${sorted === "none" ? "" : sorted === "ascending" ? " ▲" : " ▼"}</button></th>`;
  }).join("");
  const body = rows.map((r) => `<tr class="clickable" tabindex="0" data-nid="${r.nid}">${TABLE_COLS.map((k) =>
    k === "name" ? `<td>${escapeHtml(r.name)}</td>` : `<td class="n">${COL_LABEL[k] ? fmtInt(r[k]) : fmtMetric(k, r[k])}</td>`).join("")}</tr>`).join("");
  const el = document.getElementById("table-view");
  el.innerHTML = `<h2 style="margin-top:0">All neighborhoods</h2>
    <p class="small muted">Select a column heading to sort it. Select a row (or press Enter on it) to see it on the map.</p>
    <div class="table-wrap"><table><caption class="visually-hidden">Neighborhood metrics</caption><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  el.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    state.sortDir = state.sortKey === k ? -state.sortDir : (k === "name" ? 1 : -1);
    state.sortKey = k;
    renderTable();
    el.querySelector(`[data-sort="${k}"]`).focus();
  }));
  el.querySelectorAll("tr[data-nid]").forEach((tr) => {
    const go = () => { setView(false); select(Number(tr.dataset.nid), { pan: true }); };
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  });
}
function setView(table) {
  document.getElementById("table-view").hidden = !table;
  const btn = document.getElementById("view-toggle");
  btn.textContent = table ? "Show map" : "Show as table";
  btn.setAttribute("aria-pressed", String(table));
  if (table) renderTable(); else map.invalidateSize();
}

// ------------------------------------------------------------------ init
async function init() {
  const { city, cities } = await currentCity();
  setupCityNav(cities, city.slug);
  data = await loadCity(city.slug);
  features = data.neighborhoods.features;
  medians = Object.fromEntries(Object.keys(METRICS).map((k) => [k, median(features.map((f) => f.properties[k]))]));
  const s = data.summary;

  document.title = `${s.city.short_name} map · Park Access to Pro Sports`;
  document.getElementById("city-title").textContent = s.city.name;
  document.getElementById("city-sub").textContent = `${fmtInt(s.totals.neighborhoods)} neighborhoods · ${fmtInt(s.totals.pop)} residents · ${fmtInt(s.totals.pros)} pro athletes`;

  // layer radio buttons, grouped by step
  document.getElementById("layer-options").innerHTML = MAP_LAYERS.map((k) => `
    <label class="layer-option"><input type="radio" name="layer" value="${k}" ${k === state.metric ? "checked" : ""}>
      <span>${escapeHtml(METRICS[k].short)}<span class="step-tag">${STEPS[METRICS[k].step]}</span></span></label>`).join("");
  document.querySelectorAll("input[name=layer]").forEach((r) => r.addEventListener("change", () => { state.metric = r.value; restyle(); }));

  // map
  map = L.map("map", { zoomControl: true, maxZoom: 16 }).setView(s.city.map.center, s.city.map.zoom);
  // Esri gray canvas basemap (no API key). Place-name labels go in a pane above
  // the colored neighborhoods so they stay readable.
  const tone = dark ? "Dark" : "Light";
  const esri = (layer) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${tone}_Gray_${layer}/MapServer/tile/{z}/{y}/{x}`;
  const attribution = 'Basemap &copy; <a href="https://www.esri.com/">Esri</a>, HERE, Garmin, &copy; OpenStreetMap contributors';
  L.tileLayer(esri("Base"), { attribution, maxZoom: 16 }).addTo(map);
  map.createPane("labels");
  map.getPane("labels").style.zIndex = 650;
  map.getPane("labels").style.pointerEvents = "none";
  L.tileLayer(esri("Reference"), { pane: "labels", maxZoom: 16 }).addTo(map);
  renderLegend();
  geoLayer = L.geoJSON(data.neighborhoods, {
    style: styleFor,
    onEachFeature: (f, layer) => {
      layer.on("click", () => select(f.properties.nid));
      layer.bindTooltip(() => `<strong>${escapeHtml(f.properties.name)}</strong><br>${escapeHtml(METRICS[state.metric].short)}: ${fmtMetric(state.metric, f.properties[state.metric])}`, { sticky: true });
    },
  }).addTo(map);
  map.fitBounds(geoLayer.getBounds(), { padding: [10, 10] });
  renderAthletes();

  document.getElementById("toggle-athletes").addEventListener("change", renderAthletes);
  document.getElementById("athlete-filter").addEventListener("change", () => {
    document.getElementById("toggle-athletes").checked = true; renderAthletes();
  });
  document.getElementById("toggle-parks").addEventListener("change", toggleParks);
  document.getElementById("view-toggle").addEventListener("click", () => setView(document.getElementById("table-view").hidden));

  // search
  const names = new Map(features.map((f) => [f.properties.name, f.properties.nid]));
  document.getElementById("nb-names").innerHTML = [...names.keys()].sort().map((n) => `<option value="${escapeHtml(n)}">`).join("");
  const search = document.getElementById("nb-search");
  const trySelect = () => { if (names.has(search.value)) { setView(false); select(names.get(search.value), { pan: true }); } };
  search.addEventListener("change", trySelect);
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") trySelect(); });

  const m = location.hash.match(/n=(\d+)/);
  if (m && features.some((f) => f.properties.nid === Number(m[1]))) select(Number(m[1]), { pan: true });
}

init().catch((err) => showError(document.getElementById("detail"), err));
