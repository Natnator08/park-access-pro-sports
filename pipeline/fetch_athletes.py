"""Pro athletes who attended high school in the city's area, from Wikidata (CC0).

"Pro" = played for a team in one of the major North American leagues below.
High-school location is used as a stand-in for where an athlete grew up.
Schools are tagged public (Wikidata "public school" or a public NCES id) or
private; public schools mostly draw students from their surrounding area.
"""
from __future__ import annotations

import io

import geopandas as gpd
import numpy as np
import pandas as pd

from common import get, log, raw_dir

SPARQL = "https://query.wikidata.org/sparql"
LEAGUES = {
    "Q155223": ("NBA", "Basketball"),
    "Q2593221": ("WNBA", "Basketball"),
    "Q1215884": ("NFL", "Football"),
    "Q1163715": ("MLB", "Baseball"),
    "Q18543": ("MLS", "Soccer"),
    "Q1101443": ("NWSL", "Soccer"),
    "Q1215892": ("NHL", "Hockey"),
}

QUERY = """
SELECT ?p ?pLabel ?s ?sLabel ?c ?league0 (YEAR(?born) AS ?birthYear) ?article ?nces ?publicTag WHERE {
  SERVICE wikibase:box {
    ?s wdt:P625 ?c .
    bd:serviceParam wikibase:cornerSouthWest "Point(%(w)s %(s)s)"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point(%(e)s %(n)s)"^^geo:wktLiteral .
  }
  ?s wdt:P31/wdt:P279* wd:Q159334 .              # secondary school (incl. high schools)
  ?p wdt:P69 ?s ; wdt:P54 ?team .
  ?team wdt:P118 ?league .
  VALUES ?league0 { %(leagues)s }
  ?league wdt:P361* ?league0 .                   # e.g. NL West -> National League -> MLB
  OPTIONAL { ?p wdt:P569 ?born . }
  OPTIONAL { ?s wdt:P2484 ?nces . }                # NCES school ID (12 digits = public)
  BIND(EXISTS { ?s wdt:P31 wd:Q1080794 } AS ?publicTag)
  OPTIONAL { ?article schema:about ?p ; schema:isPartOf <https://en.wikipedia.org/> . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def athletes(cfg: dict) -> gpd.GeoDataFrame:
    cache = raw_dir(cfg) / "athletes_wikidata.csv"
    if not cache.exists():
        w, s, e, n = cfg["bbox"]
        q = QUERY % {"w": w, "s": s, "e": e, "n": n,
                     "leagues": " ".join(f"wd:{k}" for k in LEAGUES)}
        log("querying Wikidata for pro athletes by high school")
        r = get(SPARQL, params={"query": q}, headers={"Accept": "text/csv"}, timeout=300)
        cache.write_text(r.text)
    df = pd.read_csv(io.StringIO(cache.read_text()), dtype={"nces": str, "publicTag": str})
    if df.empty:
        return gpd.GeoDataFrame(columns=["id", "name", "school", "school_type", "leagues", "sports", "birth_year", "url", "geometry"], crs=4326)

    df["id"] = df["p"].str.rsplit("/", n=1).str[-1]
    df["school_id"] = df["s"].str.rsplit("/", n=1).str[-1]
    league_id = df["league0"].str.rsplit("/", n=1).str[-1]
    df["league"] = league_id.map(lambda k: LEAGUES[k][0])
    df["sport"] = league_id.map(lambda k: LEAGUES[k][1])
    xy = df["c"].str.extract(r"Point\(([-\d.]+) ([-\d.]+)\)").astype(float)
    df["lon"], df["lat"] = xy[0], xy[1]
    # Drop items with no English label (label falls back to the Q-id).
    df = df[~df["pLabel"].str.fullmatch(r"Q\d+")]

    # Public vs private. Public NCES ids are 12 digits starting with the state FIPS.
    nces = df["nces"].fillna("").str.strip()
    public_id = nces.str.fullmatch(r"\d{12}")
    wrong_state = public_id & (nces.str[:2] != cfg["state_fips"])
    if wrong_state.any():
        bad = sorted(df.loc[wrong_state, "sLabel"].unique())
        log(f"dropping schools whose NCES id is in another state (bad coordinates): {bad}")
        df = df[~wrong_state]
        public_id = public_id[~wrong_state]
    tag = df["publicTag"].fillna("").str.lower().isin(["true", "1"])
    df["school_type"] = np.where(tag | public_id, "public", "private")

    # One row per athlete. If they attended several local high schools,
    # keep the one listed first (sorted by school id for reproducibility).
    agg = (df.sort_values(["id", "school_id"])
             .groupby("id")
             .agg(name=("pLabel", "first"), school=("sLabel", "first"),
                  school_type=("school_type", "first"), lat=("lat", "first"), lon=("lon", "first"),
                  leagues=("league", lambda x: sorted(set(x))),
                  sports=("sport", lambda x: sorted(set(x))),
                  birth_year=("birthYear", "min"), url=("article", "first"))
             .reset_index())
    g = gpd.GeoDataFrame(agg, geometry=gpd.points_from_xy(agg.lon, agg.lat), crs=4326)
    log(f"{len(g):,} pro athletes linked to {df['school_id'].nunique():,} high schools in the search box")
    return g
