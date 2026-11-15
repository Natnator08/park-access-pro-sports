"""Parks and sports facilities.

  * Trust for Public Land ParkServe: public park polygons and the
    10-minute-walk service area around each park (walking network based).
  * OpenStreetMap (Overpass API): sports pitches, courts, tracks, sports centres.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd

from common import arcgis_query, features_to_gdf, get, log, raw_dir

PARKSERVE = "https://server7.tplgis.org/arcgis7/rest/services/ParkServe/ParkServe_ProdNew/MapServer"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
PARK_FIELDS = "parkid,park_name,park_size_acres,park_designation,park_owner_type,park_county_fips,playground_count"


def _cached_layer(cfg: dict, name: str, layer: int, out_fields: str) -> gpd.GeoDataFrame:
    cache = raw_dir(cfg) / f"{name}.parquet"
    if cache.exists():
        return gpd.read_parquet(cache)
    log(f"fetching ParkServe {name}")
    g = features_to_gdf(arcgis_query(f"{PARKSERVE}/{layer}", bbox=cfg["bbox"], out_fields=out_fields))
    g["geometry"] = g.geometry.make_valid()
    g.to_parquet(cache)
    return g


def parks(cfg: dict) -> gpd.GeoDataFrame:
    g = _cached_layer(cfg, "parks", 2, PARK_FIELDS).drop_duplicates("parkid")
    log(f"{len(g):,} parks with public access")
    return g


def walk_areas(cfg: dict) -> gpd.GeoDataFrame:
    g = _cached_layer(cfg, "walk_areas", 3, "parkid")
    log(f"{len(g):,} 10-minute walk service areas")
    return g


def sports_facilities(cfg: dict) -> gpd.GeoDataFrame:
    cache = raw_dir(cfg) / "osm_sports.json"
    if not cache.exists():
        w, s, e, n = cfg["bbox"]
        query = f"""
[out:json][timeout:300];
nwr["leisure"~"^(pitch|sports_centre|track|stadium)$"]({s},{w},{n},{e});
out center tags;"""
        last_err = None
        for url in OVERPASS_URLS:
            try:
                log(f"querying OpenStreetMap sports facilities via {url}")
                r = get(url, params={"data": query}, timeout=400, retries=2)
                cache.write_text(r.text)
                break
            except Exception as err:  # try the next mirror
                last_err = err
        else:
            raise RuntimeError(f"All Overpass mirrors failed: {last_err}")
    rows = []
    for el in json.loads(cache.read_text())["elements"]:
        tags = el.get("tags", {})
        if tags.get("access") in ("private", "no"):
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        rows.append({"leisure": tags.get("leisure"), "sport": tags.get("sport", ""), "lat": lat, "lon": lon})
    df = pd.DataFrame(rows)
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=4326)
    log(f"{len(g):,} publicly accessible sports facilities (OSM)")
    return g
