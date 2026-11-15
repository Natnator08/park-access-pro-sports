// Shared data loading, metric definitions, and formatting. No city is
// hardcoded here: everything comes from data/cities.json and data/<slug>/.

export const STEPS = {
  income: "Context",
  access: "Step 1 · Park access",
  participation: "Step 2 · Youth sports",
  pros: "Step 3 · Going pro",
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
};

const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function fmt(value, kind) {
  if (value === null || value === undefined || Number.isNaN(value)) return "No data";
  switch (kind) {
    case "money": return money.format(value);
    case "pct": return `${Math.round(value * 100)}%`;
    case "dec1": return nf1.format(value);
    default: return nf0.format(value);
  }
}
export const fmtMetric = (key, v) => fmt(v, METRICS[key]?.fmt);
export const fmtInt = (v) => nf0.format(v);

export function compact(v) {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

const cache = new Map();
async function getJSON(url) {
  if (!cache.has(url)) {
    cache.set(url, fetch(url).then((r) => {
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
