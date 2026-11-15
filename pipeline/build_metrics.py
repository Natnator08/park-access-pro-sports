"""Combine all sources into neighborhood metrics + summary statistics.

Method in brief (full version on the site's Methodology page):
  * 2020 census blocks are the building unit. Each populated block's interior
    point is assigned to a neighborhood, and tract-level ACS counts are split
    across the tract's blocks in proportion to 2020 block population.
  * Park access = share of residents whose block lies inside a ParkServe
    10-minute-walk service area.
  * Estimated sports participation = the tract's kids (6-17) in each income
    bracket x the state participation rate for that bracket (NSCH).
  * Pro athletes are counted where their high school is.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from common import arcgis_query, features_to_gdf, log, raw_dir
from fetch_participation import BRACKETS

MIN_POP_RELIABLE = 10_000     # below this, per-capita athlete rates are flagged
MIN_POP_FOR_STATS = 5_000     # neighborhoods smaller than this are left out of correlations
RECENT_BIRTH_YEAR = 1985      # "recent era" athletes (high school ~2000 onward)
# ParkServe designations left out of "close-to-home" park acres: national forests,
# national recreation areas, wildlife refuges, state parks. They are huge and
# would swamp the per-resident numbers for the neighborhoods that border them.
REMOTE_PARK_DESIGNATIONS = {"NF", "NRA", "NWR", "SP"}

METRICS = {
    "median_income": "Median household income",
    "child_poverty_pct": "Kids in poverty",
    "walk_access_pct": "Residents within a 10-min walk of a park",
    "park_acres_per_1k": "Close-to-home park acres per 1,000 residents",
    "facilities_per_1k_kids": "Sports courts & fields in public parks per 1,000 kids",
    "est_participation": "Est. kids in organized sports",
    "pros_per_100k": "Pro athletes per 100k residents (all eras)",
    "pros_public_per_100k": "Pro athletes per 100k residents (public high schools)",
    "pros_recent_per_100k": f"Pro athletes per 100k residents (born {RECENT_BIRTH_YEAR}+)",
}


# --------------------------------------------------------------------------- geography
def neighborhood_shapes(cfg: dict) -> gpd.GeoDataFrame | None:
    """Raw neighborhood polygons from the configured source (cached), or None for tracts."""
    n = cfg["neighborhoods"]
    if n["type"] == "tracts":
        return None
    cache = raw_dir(cfg) / "neighborhoods.parquet"
    if cache.exists():
        return gpd.read_parquet(cache)
    if n["type"] == "arcgis":
        g = features_to_gdf(arcgis_query(n["url"], where=n.get("where", "1=1"), out_fields=n["name_field"]))
    elif n["type"] == "geojson":
        g = gpd.read_file(n["url"]).to_crs(4326)
    else:
        raise ValueError(f"Unknown neighborhoods type {n['type']!r}")
    g = g.rename(columns={n["name_field"]: "name"})
    g["name"] = g["name"].astype(str).str.strip()
    if n.get("title_case"):
        g["name"] = g["name"].str.title()
    g["geometry"] = g.geometry.make_valid()
    g = g.dissolve("name", as_index=False)[["name", "geometry"]]
    g.to_parquet(cache)
    return g


def neighborhoods(cfg: dict, tracts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = neighborhood_shapes(cfg)
    if g is None:
        g = tracts[["GEOID", "geometry"]].rename(columns={"GEOID": "name"})
        g["name"] = "Tract " + g["name"].str[5:]
    # Clip to the city's tracts so neighbors outside the counties are dropped.
    area = tracts.union_all()
    g = g[g.intersects(area)].copy()
    g["geometry"] = g.geometry.intersection(area)
    g = g[~g.geometry.is_empty].reset_index(drop=True)
    g.insert(0, "nid", np.arange(len(g)))
    log(f"{len(g):,} neighborhoods")
    return g


def assign_points(points: gpd.GeoDataFrame, polys: gpd.GeoDataFrame, crs) -> pd.Series:
    """Neighborhood id for each point; points in gaps snap to the nearest polygon."""
    j = gpd.sjoin(points[["geometry"]], polys[["nid", "geometry"]], predicate="within", how="left")
    j = j[~j.index.duplicated()]
    miss = j["nid"].isna()
    if miss.any():
        near = gpd.sjoin_nearest(points.loc[miss, ["geometry"]].to_crs(crs),
                                 polys[["nid", "geometry"]].to_crs(crs), max_distance=500)
        near = near[~near.index.duplicated()]
        j.loc[near.index, "nid"] = near["nid"]
    return j["nid"]


# --------------------------------------------------------------------------- statistics
def _spearman(x: pd.Series, y: pd.Series) -> dict:
    m = x.notna() & y.notna()
    rho, p = stats.spearmanr(x[m], y[m])
    return {"rho": round(float(rho), 3), "p": float(p), "n": int(m.sum())}


def _partial_spearman(x: pd.Series, y: pd.Series, control: pd.Series) -> dict:
    """Spearman correlation of x and y after removing the (rank) effect of control."""
    m = x.notna() & y.notna() & control.notna()
    rx, ry, rc = (s[m].rank() for s in (x, y, control))
    resid = lambda a: a - np.polyval(np.polyfit(rc, a, 1), rc)  # noqa: E731
    r, _ = stats.pearsonr(resid(rx), resid(ry))
    n = int(m.sum())
    t = r * np.sqrt((n - 3) / max(1e-12, 1 - r**2))
    p = 2 * stats.t.sf(abs(t), n - 3)
    return {"rho": round(float(r), 3), "p": float(p), "n": n}


def income_groups(nb: pd.DataFrame, k: int = 5) -> list[dict]:
    """Split neighborhoods into k groups with ~equal population, by median income."""
    d = nb[nb["median_income"].notna() & (nb["pop"] > 0)].sort_values("median_income")
    share = d["pop"].cumsum() / d["pop"].sum()
    d = d.assign(group=np.minimum((share * k - 1e-9).astype(int), k - 1))
    out = []
    for gi, g in d.groupby("group"):
        pop, kids, kids6 = g["pop"].sum(), g["kids0_17"].sum(), g["kids6_17"].sum()
        out.append({
            "group": int(gi) + 1,
            "label": ["Lowest", "Lower-middle", "Middle", "Upper-middle", "Highest"][gi] if k == 5 else f"Group {gi + 1}",
            "income_min": int(g["median_income"].min()), "income_max": int(g["median_income"].max()),
            "neighborhoods": int(len(g)), "pop": int(pop),
            "walk_access_pct": round(g["pop_in_walk"].sum() / g["pop2020"].sum(), 4),
            "park_acres_per_1k": round(g["park_acres"].sum() / pop * 1000, 2),
            "facilities_per_1k_kids": round(g["facilities"].sum() / kids * 1000, 2),
            "est_participation": round(g["participants"].sum() / kids6, 4),
            "child_poverty_pct": round(g["kids_in_poverty"].sum() / kids, 4),
            "pros": int(g["pros"].sum()), "pros_recent": int(g["pros_recent"].sum()),
            "pros_public": int(g["pros_public"].sum()),
            "pros_public_per_100k": round(g["pros_public"].sum() / pop * 1e5, 2),
            "pros_per_100k": round(g["pros"].sum() / pop * 1e5, 2),
            "pros_recent_per_100k": round(g["pros_recent"].sum() / pop * 1e5, 2),
        })
    return out


# --------------------------------------------------------------------------- main
def build(cfg, tracts, acs, blocks, parks, walk, facilities, athletes, participation):
    crs = tracts.estimate_utm_crs()
    nb = neighborhoods(cfg, tracts)

    # ---- blocks: neighborhood, walk access, and tract-share weights
    blocks = blocks[blocks["tract"].isin(tracts["GEOID"])].copy()
    blocks["nid"] = assign_points(blocks, nb, crs)
    lost = blocks["nid"].isna()
    if lost.any():
        log(f"warning: {blocks.loc[lost, 'pop2020'].sum():,.0f} residents fell outside every neighborhood")
    blocks = blocks[~lost].copy()
    blocks["nid"] = blocks["nid"].astype(int)
    in_walk = gpd.sjoin(blocks[["geometry"]], walk[["geometry"]], predicate="within").index.unique()
    blocks["in_walk"] = blocks.index.isin(in_walk)
    blocks["w"] = blocks["pop2020"] / blocks.groupby("tract")["pop2020"].transform("sum")

    # ---- spread tract ACS counts onto blocks
    rate = {b: participation["brackets"][b]["rate"] for b in BRACKETS}
    acs = acs.copy()
    acs["participants"] = sum(acs[f"kids6_17_{b}"] * rate[b] for b in BRACKETS)
    count_cols = ["pop", "kids0_17", "kids6_17", "kids_in_poverty", "participants"]
    b = blocks.join(acs[count_cols + ["median_income"]], on="tract")
    for c in count_cols:
        b[c] = b[c] * b["w"]
    b["inc_x_pop"] = b["median_income"] * b["pop"]
    b["pop_with_inc"] = b["pop"].where(b["median_income"].notna(), 0)
    b["pop_in_walk"] = b["pop2020"].where(b["in_walk"], 0)
    agg = b.groupby("nid")[count_cols + ["inc_x_pop", "pop_with_inc", "pop2020", "pop_in_walk"]].sum(min_count=1)

    # ---- parks: acres inside each neighborhood
    nb_p = nb.to_crs(crs)
    local = parks[~parks["park_designation"].isin(REMOTE_PARK_DESIGNATIONS)]
    inter = gpd.overlay(local[["geometry"]].to_crs(crs), nb_p[["nid", "geometry"]], how="intersection", keep_geom_type=True)
    inter["acres"] = inter.area / 4046.8564224
    park_acres = inter.groupby("nid")["acres"].sum()

    # ---- sports facilities and athletes
    # Only count courts/fields inside public parks. School fields are excluded on
    # purpose: athletes are located by high school, so counting school fields would
    # mechanically link "facilities" and "pro athletes".
    in_park = gpd.sjoin(facilities[["geometry"]], parks[["geometry"]], predicate="within").index.unique()
    log(f"{len(in_park):,} of {len(facilities):,} OSM sports facilities are inside public parks")
    facilities = facilities.loc[in_park]
    facilities = facilities.assign(nid=assign_points(facilities, nb, crs)).dropna(subset=["nid"])
    fac_count = facilities.groupby(facilities["nid"].astype(int)).size()
    athletes = athletes.assign(nid=assign_points(athletes, nb, crs))
    athletes = athletes[athletes["nid"].notna()].copy()
    athletes["nid"] = athletes["nid"].astype(int)
    pros = athletes.groupby("nid").size()
    pros_recent = athletes[athletes["birth_year"] >= RECENT_BIRTH_YEAR].groupby("nid").size()
    pros_public = athletes[athletes["school_type"] == "public"].groupby("nid").size()

    # ---- assemble neighborhood table
    nb = nb.join(agg, on="nid")
    nb["park_acres"] = nb["nid"].map(park_acres).fillna(0)
    nb["facilities"] = nb["nid"].map(fac_count).fillna(0)
    nb["pros"] = nb["nid"].map(pros).fillna(0).astype(int)
    nb["pros_recent"] = nb["nid"].map(pros_recent).fillna(0).astype(int)
    nb["pros_public"] = nb["nid"].map(pros_public).fillna(0).astype(int)
    nb = nb[nb["pop"].fillna(0) >= 100].copy()  # drop empty areas (parks, airports, ...)

    safe = lambda num, den: (num / den).where(den > 0)  # noqa: E731
    nb["median_income"] = safe(nb["inc_x_pop"], nb["pop_with_inc"])
    nb["child_poverty_pct"] = safe(nb["kids_in_poverty"], nb["kids0_17"])
    nb["walk_access_pct"] = safe(nb["pop_in_walk"], nb["pop2020"])
    nb["park_acres_per_1k"] = safe(nb["park_acres"] * 1000, nb["pop"])
    nb["facilities_per_1k_kids"] = safe(nb["facilities"] * 1000, nb["kids0_17"])
    nb["est_participation"] = safe(nb["participants"], nb["kids6_17"])
    nb["pros_per_100k"] = safe(nb["pros"] * 1e5, nb["pop"])
    nb["pros_recent_per_100k"] = safe(nb["pros_recent"] * 1e5, nb["pop"])
    nb["pros_public_per_100k"] = safe(nb["pros_public"] * 1e5, nb["pop"])
    nb["reliable"] = nb["pop"] >= MIN_POP_RELIABLE

    # ---- statistics
    s = nb[nb["pop"] >= MIN_POP_FOR_STATS]
    pairs = [
        ("walk_access_pct", "pros_per_100k"), ("walk_access_pct", "pros_public_per_100k"),
        ("walk_access_pct", "pros_recent_per_100k"),
        ("park_acres_per_1k", "pros_public_per_100k"), ("facilities_per_1k_kids", "pros_public_per_100k"),
        ("median_income", "pros_public_per_100k"),
        ("park_acres_per_1k", "pros_per_100k"), ("facilities_per_1k_kids", "pros_per_100k"),
        ("facilities_per_1k_kids", "pros_recent_per_100k"),
        ("median_income", "walk_access_pct"), ("median_income", "park_acres_per_1k"),
        ("median_income", "facilities_per_1k_kids"),
        ("median_income", "pros_per_100k"), ("median_income", "pros_recent_per_100k"),
        ("est_participation", "pros_per_100k"),
    ]
    correlations = [{"x": x, "y": y, **_spearman(s[x], s[y])} for x, y in pairs]
    partial = [{"x": x, "y": y, "control": "median_income", **_partial_spearman(s[x], s[y], s["median_income"])}
               for x, y in [("walk_access_pct", "pros_per_100k"), ("walk_access_pct", "pros_public_per_100k"),
                            ("walk_access_pct", "pros_recent_per_100k"), ("park_acres_per_1k", "pros_public_per_100k"),
                            ("facilities_per_1k_kids", "pros_public_per_100k"),
                            ("facilities_per_1k_kids", "pros_per_100k"),
                            ("facilities_per_1k_kids", "pros_recent_per_100k"),
                            ("park_acres_per_1k", "pros_per_100k")]]

    totals = {
        "pop": int(nb["pop"].sum()), "kids0_17": int(nb["kids0_17"].sum()),
        "neighborhoods": int(len(nb)), "tracts": int(len(tracts)), "blocks": int(len(blocks)),
        "parks": int(len(parks)), "facilities": int(nb["facilities"].sum()),
        "pros": int(nb["pros"].sum()), "pros_recent": int(nb["pros_recent"].sum()),
        "pros_public": int(nb["pros_public"].sum()),
        "walk_access_pct": round(nb["pop_in_walk"].sum() / nb["pop2020"].sum(), 4),
        "est_participation": round(nb["participants"].sum() / nb["kids6_17"].sum(), 4),
        "pros_per_100k": round(nb["pros"].sum() / nb["pop"].sum() * 1e5, 2),
    }
    summary = {
        "totals": totals, "income_groups": income_groups(nb), "correlations": correlations,
        "partial_correlations": partial, "participation": participation, "metrics": METRICS,
        "thresholds": {"min_pop_reliable": MIN_POP_RELIABLE, "min_pop_for_stats": MIN_POP_FOR_STATS,
                       "recent_birth_year": RECENT_BIRTH_YEAR,
                       "remote_park_designations": sorted(REMOTE_PARK_DESIGNATIONS)},
        "stats_sample": int(len(s)),
    }
    return nb, athletes, summary
