// Shared data loading, metric definitions, and formatting. No city is
// hardcoded here: everything comes from data/cities.json and data/<slug>/.

export const STEPS = {
  income: "Context",
  access: "Step 1 · Park access",
  participation: "Step 2 · Youth sports",
  pros: "Step 3 · Going pro",
  people: "Who lives here",
};

// Display settings for each metric produced by the pipeline.
// `better`: which direction is favorable for kids (used only in wording).
export const METRICS = {
  median_income: { step: "income", short: "Median household income", fmt: "money", better: "high" },
  child_poverty_pct: { step: "income", short: "Kids in poverty", fmt: "pct", better: "low" },
  walk_access_pct: { step: "access", short: "Residents within a 10-min walk of a park", fmt: "pct", better: "high" },
  park_acres_per_1k: { step: "access", short: "Park acres per 1,000 residents", fmt: "dec1", better: "high", skewed: true },
  facilities_per_1k_kids: { step: "access", short: "Park courts & fields per 1,000 kids", fmt: "dec1", better: "high", skewed: true },
  est_participation: { step: "participation", short: "Est. kids in organized sports", fmt: "pct", better: "high", estimate: true },
  pros_per_100k: { step: "pros", short: "Pro athletes per 100k residents", fmt: "dec1", better: "high", skewed: true, rate: "pros" },
  pros_public_per_100k: { step: "pros", short: "Pro athletes per 100k (public high schools)", fmt: "dec1", better: "high", skewed: true, rate: "pros_public" },
  pros_recent_per_100k: { step: "pros", short: "Pro athletes per 100k (born 1985+)", fmt: "dec1", better: "high", skewed: true, rate: "pros_recent" },
  // Demographics (ACS). Not "better" or "worse": shown for context only.
  pct_hispanic: { step: "people", short: "Hispanic or Latino residents", fmt: "pct" },
  pct_white: { step: "people", short: "White residents (non-Hispanic)", fmt: "pct" },
  pct_black: { step: "people", short: "Black residents (non-Hispanic)", fmt: "pct" },
  pct_asian: { step: "people", short: "Asian residents (non-Hispanic)", fmt: "pct" },
  pct_0_17: { step: "people", short: "Residents under 18", fmt: "pct" },
  pct_65p: { step: "people", short: "Residents 65 and older", fmt: "pct" },
  median_age: { step: "people", short: "Median age (approx.)", fmt: "dec1" },
};

// Demographic groups in display order. Race/ethnicity groups are mutually exclusive:
// Hispanic or Latino of any race, then non-Hispanic people by race.
export const RACE_GROUPS = [
  ["hispanic", "Hispanic or Latino"], ["white", "White"], ["black", "Black"], ["asian", "Asian"],
  ["other", "Other or multiracial"], ["native", "Native American"], ["pacific", "Pacific Islander"],
];
export const AGE_GROUPS = [["0_17", "Under 18"], ["18_34", "18–34"], ["35_64", "35–64"], ["65p", "65+"]];

/**
 * A thin segmented bar (one whole split into parts) with a legend that carries the
 * names and percentages, so identity never relies on color alone.
 * parts: [{label, value (0-1), color}]
 */
export function segmentedBar(parts, ariaLabel) {
  const shown = parts.filter((p) => p.value > 0);
  const desc = shown.map((p) => `${p.label} ${Math.round(p.value * 100)}%`).join(", ");
  return `<div class="seg-bar" role="img" aria-label="${escapeHtml(ariaLabel)}: ${escapeHtml(desc)}">${
    shown.map((p) => `<span style="flex:${p.value} 1 0;background:${p.color}" title="${escapeHtml(p.label)}: ${fmt(p.value, "pct1")}"></span>`).join("")}</div>
    <ul class="seg-legend">${parts.map((p) => `<li><span class="swatch-dot" style="background:${p.color}" aria-hidden="true"></span>${escapeHtml(p.label)} <strong>${escapeHtml(fmt(p.value, "pct1"))}</strong></li>`).join("")}</ul>`;
}
export function raceParts(get) {
  return RACE_GROUPS.map(([k, label], i) => ({ label, value: get(k) ?? 0, color: `var(--cat-${i + 1})` }));
}
export function ageParts(get) {
  return AGE_GROUPS.map(([k, label], i) => ({ label, value: get(k) ?? 0, color: `var(--ord-${i + 2})` }));
}

const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function fmt(value, kind) {
  if (value === null || value === undefined || Number.isNaN(value)) return "No data";
  switch (kind) {
    case "money": return money.format(value);
    case "pct": return `${Math.round(value * 100)}%`;
    case "pct1": return value > 0 && value < 0.01 ? "<1%" : `${Math.round(value * 100)}%`;
    case "dec1": return nf1.format(value);
    default: return nf0.format(value);
  }
}
export const fmtMetric = (key, v) => fmt(v, METRICS[key]?.fmt);
export const fmtInt = (v) => nf0.format(v);

export function compact(v) {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

// Replaced with the commit id at deploy time (see .github/workflows/pages.yml),
// so browsers never mix cached files from different versions of the site.
export const VERSION = "__VERSION__";

const cache = new Map();
async function getJSON(url) {
  if (!cache.has(url)) {
    cache.set(url, fetch(`${url}?v=${VERSION}`).then((r) => {
      if (!r.ok) throw new Error(`Could not load ${url} (${r.status})`);
      return r.json();
    }));
  }
  return cache.get(url);
}

export const loadCities = () => getJSON("data/cities.json");

export async function loadCity(slug) {
  const base = `data/${encodeURIComponent(slug)}`;
  const [summary, neighborhoods, athletes] = await Promise.all([
    getJSON(`${base}/summary.json`),
    getJSON(`${base}/neighborhoods.geojson`),
    getJSON(`${base}/athletes.json`),
  ]);
  return { summary, neighborhoods, athletes, parksUrl: `${base}/parks.geojson` };
}
export const loadParks = (url) => getJSON(url);

/** Which city to show: ?city=… if valid, else the first built city. */
export async function currentCity() {
  const cities = await loadCities();
  const wanted = new URLSearchParams(location.search).get("city");
  const city = cities.find((c) => c.slug === wanted) ?? cities[0];
  return { city, cities };
}

/** Fill the header city picker and keep ?city= on the nav links. */
export function setupCityNav(cities, slug) {
  const sel = document.getElementById("city-select");
  if (sel) {
    sel.innerHTML = cities.map((c) => `<option value="${c.slug}">${escapeHtml(c.short_name)}</option>`).join("");
    sel.value = slug;
    sel.addEventListener("change", () => {
      const u = new URL(location.href);
      u.searchParams.set("city", sel.value);
      location.href = u.toString();
    });
  }
  document.querySelectorAll("[data-city-link]").forEach((a) => {
    const u = new URL(a.getAttribute("href"), location.href);
    u.searchParams.set("city", slug);
    a.href = u.pathname.split("/").pop() + u.search;
  });
}

export function median(values) {
  const v = values.filter((x) => x !== null && x !== undefined && !Number.isNaN(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Plain-language description of a Spearman correlation. */
export function describeCorrelation(rho, p) {
  const a = Math.abs(rho);
  const strength = a < 0.1 ? "No meaningful" : a < 0.3 ? "A weak" : a < 0.5 ? "A moderate" : "A strong";
  const dir = a < 0.1 ? "" : rho > 0 ? " positive" : " negative";
  const sig = p < 0.05 ? "unlikely to be chance (p < 0.05)" : "could easily be chance";
  return { strength: `${strength}${dir} relationship`, sig };
}

export function showError(el, err) {
  console.error(err);
  el.innerHTML = `<div class="callout caution"><strong>Couldn't load the data.</strong>
    <p class="small">${escapeHtml(err.message)}. If you opened this file directly, serve the
    <code>site/</code> folder with a local web server instead (see README).</p></div>`;
}

/**
 * Compare the lowest- and highest-income groups on a "more is better" measure.
 * Returns how the lowest group compares: "less" (it has less), "more", or "same".
 */
export function gap(low, high) {
  if (!low || !high) return { dir: low === high ? "same" : (low ? "more" : "less"), n: null, text: "" };
  const r = high / low;
  const dir = r >= 1.15 ? "less" : r <= 1 / 1.15 ? "more" : "same";
  const n = dir === "less" ? r : dir === "more" ? 1 / r : 1;
  return { dir, n, text: n >= 10 ? n.toFixed(0) : n.toFixed(1) };
}
