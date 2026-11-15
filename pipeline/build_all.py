"""Build all site data for one city.

    .venv/bin/python pipeline/build_all.py --city los-angeles

Downloads are cached in data_raw/ so re-runs are fast. Delete a cached
file to refresh that source.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math

import geopandas as gpd
import shapely

import build_metrics
import demographics
import fetch_athletes
import fetch_census
import fetch_parks
import fetch_participation
from common import SITE_DATA_DIR, load_city, log, write_json

ROUND = {"median_income": 0, "pop": 0, "kids0_17": 0, "kids6_17": 0, "park_acres": 1,
         "facilities": 0, "pros": 0, "pros_recent": 0, "pros_public": 0, "median_age": 1}


def _clean(v, nd=4):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, float):
        return int(round(v)) if nd == 0 else round(v, nd)
    return v.item() if hasattr(v, "item") else v


def _geo(g, tolerance):
    g = g.copy()
    g["geometry"] = shapely.set_precision(g.geometry.simplify(tolerance, preserve_topology=True), 1e-5)
    return g[~g.geometry.is_empty]


def write_outputs(cfg, nb, athletes, parks, summary):
    out = SITE_DATA_DIR / cfg["slug"]
    props = ["nid", "name", "area", "reliable", *ROUND, *build_metrics.METRICS, "median_age", *demographics.SHARES]
    props = list(dict.fromkeys(props))
    nbo = _geo(nb[props + ["geometry"]], 0.0003)
    feats = []
    for row, geom in zip(nbo[props].to_dict("records"), nbo.geometry):
        p = {k: _clean(v, ROUND.get(k, 4)) for k, v in row.items()}
        feats.append({"type": "Feature", "properties": p, "geometry": shapely.geometry.mapping(geom)})
    write_json(out / "neighborhoods.geojson", {"type": "FeatureCollection", "features": feats})

    ath = [{"name": r["name"], "school": r["school"], "school_type": r["school_type"], "leagues": r["leagues"], "sports": r["sports"],
            "birth_year": _clean(r["birth_year"], 0), "url": _clean(r["url"]) if isinstance(r["url"], str) else None,
            "lat": round(r["lat"], 5), "lon": round(r["lon"], 5), "nid": int(r["nid"])}
           for r in athletes.sort_values("name").to_dict("records")]
    write_json(out / "athletes.json", ath)

    pk = parks[parks["park_county_fips"].isin([cfg["state_fips"] + c for c in cfg["county_fips"]])]
    pk = _geo(pk[["park_name", "park_size_acres", "geometry"]], 0.0001)
    pfeats = [{"type": "Feature", "properties": {"name": n if isinstance(n, str) else "Unnamed park",
                                               "acres": _clean(float(a), 1) if a == a and a is not None else None},
               "geometry": shapely.geometry.mapping(g)}
              for n, a, g in zip(pk["park_name"], pk["park_size_acres"], pk.geometry)]
    write_json(out / "parks.geojson", {"type": "FeatureCollection", "features": pfeats})

    summary = {**summary, "city": {k: cfg[k] for k in ("slug", "name", "short_name", "description", "map")},
               "neighborhood_source": cfg["neighborhoods"].get("source", cfg["neighborhoods"]["type"]),
               "acs_year": cfg["acs_year"], "built": dt.date.today().isoformat()}
    write_json(out / "summary.json", summary)

    # Register the city in the site-wide index.
    idx_path = SITE_DATA_DIR / "cities.json"
    cities = json.loads(idx_path.read_text()) if idx_path.exists() else []
    cities = [c for c in cities if c["slug"] != cfg["slug"]]
    low = summary["income_groups"][0]
    high = summary["income_groups"][-1]
    cities.append({"slug": cfg["slug"], "name": cfg["name"], "short_name": cfg["short_name"],
                   "description": cfg.get("description", ""), "totals": summary["totals"],
                   "lowest_income_group": low, "highest_income_group": high,
                   "demographics": summary["demographics"]})
    write_json(idx_path, sorted(cities, key=lambda c: c["name"]))
    sizes = {p.name: f"{p.stat().st_size / 1e6:.1f} MB" for p in out.iterdir()}
    log(f"wrote {out}: {sizes}")


def check(cfg, tracts, nb, athletes, summary):
    """Sanity checks. Fail loudly rather than publish bad numbers."""
    t = summary["totals"]
    assert len(tracts) > 0, "no tracts"
    assert nb["median_income"].notna().mean() > 0.95, "too many neighborhoods missing income"
    assert 0.2 < t["walk_access_pct"] < 1.0, f"implausible walk access {t['walk_access_pct']}"
    assert 0.2 < t["est_participation"] < 0.9, "implausible participation"
    assert t["pros"] > 0, "no athletes matched"
    assert athletes["nid"].isin(nb["nid"]).mean() > 0.95, "athletes not matched to neighborhoods"
    # Neighborhood totals should account for (nearly) all ACS population assigned to
    # the city's blocks; a bigger gap means residents were silently dropped.
    exp = summary["_expected_pop"]
    assert abs(t["pop"] - exp) / exp < 0.02, f"population mismatch {t['pop']:,} vs expected {exp:,}"
    if not build_metrics.is_clipped(cfg):
        acs_pop = summary["_acs_pop"]
        assert abs(t["pop"] - acs_pop) / acs_pop < 0.02, f"population mismatch {t['pop']:,} vs ACS {acs_pop:,}"
    d = summary["demographics"]
    for part in ("race", "age", "sex"):
        total = sum(d[part].values())
        assert abs(total - 1) < 0.002, f"{part} shares sum to {total:.4f}, not 1"
    assert 15 < (d["median_age"] or 0) < 60, f"implausible median age {d['median_age']}"
    log("sanity checks passed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True)
    cfg = load_city(ap.parse_args().city)
    print(f"Building {cfg['name']}")

    print("1/5 Census")
    tracts = fetch_census.tracts(cfg)
    if build_metrics.is_clipped(cfg):
        # The "city" is smaller than its counties: keep every tract that overlaps the
        # city boundary (or its neighborhoods). Census blocks later decide which
        # residents of a straddling tract are actually inside the city.
        area = gpd.GeoSeries([build_metrics.coverage_shape(cfg)], crs=4326)
        crs = tracts.estimate_utm_crs()
        area_p = area.to_crs(crs).iloc[0]
        tp = tracts.to_crs(crs)
        overlap = tp.geometry.intersection(area_p).area / tp.geometry.area
        tracts = tracts[overlap.to_numpy() > 0.001].reset_index(drop=True)
        log(f"{len(tracts):,} tracts overlap the neighborhood boundaries")
    if not cfg.get("bbox"):
        cfg["bbox"] = [round(v, 3) for v in tracts.total_bounds]
    acs = fetch_census.acs(cfg)
    acs = acs[acs.index.isin(tracts["GEOID"])]
    blocks = fetch_census.blocks(cfg)
    print("2/5 Parks and sports facilities")
    parks, walk = fetch_parks.parks(cfg), fetch_parks.walk_areas(cfg)
    facilities = fetch_parks.sports_facilities(cfg)
    print("3/5 Pro athletes")
    athletes = fetch_athletes.athletes(cfg)
    print("4/5 Youth sports participation")
    participation = fetch_participation.participation_rates(cfg)
    print("5/5 Building metrics")
    nb, athletes, summary = build_metrics.build(cfg, tracts, acs, blocks, parks, walk, facilities, athletes, participation)
    summary["_acs_pop"] = int(acs["pop"].sum())
    check(cfg, tracts, nb, athletes, summary)
    del summary["_acs_pop"], summary["_expected_pop"]
    write_outputs(cfg, nb, athletes, parks, summary)

    t = summary["totals"]
    print(f"\nDone: {t['neighborhoods']} neighborhoods, {t['pop']:,} residents, "
          f"{t['walk_access_pct']:.0%} within a 10-min walk of a park, {t['pros']} pro athletes.")
    print("By income group (lowest → highest):")
    for g in summary["income_groups"]:
        print(f"  {g['label']:<13} walk {g['walk_access_pct']:.0%}  acres/1k {g['park_acres_per_1k']:>6}  "
              f"fac/1k kids {g['facilities_per_1k_kids']:>5}  sports {g['est_participation']:.0%}  "
              f"pros/100k {g['pros_per_100k']:>5} (public HS {g['pros_public_per_100k']}, recent {g['pros_recent_per_100k']})")


if __name__ == "__main__":
    main()
