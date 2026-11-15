"""Census data: tract boundaries, ACS 5-year tables, and 2020 block populations.

Uses keyless sources so anyone can rebuild the data:
  * Cartographic boundary tract shapefiles (www2.census.gov)
  * ACS table-based summary files (www2.census.gov), streamed and filtered
  * TIGERweb REST service for 2020 block populations + interior points
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from common import arcgis_query, download, get, log, raw_dir

ACS_BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/data/5YRData/acsdt5y{y}-{t}.dat"
TRACT_URL = "https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_{st}_tract_500k.zip"
TIGERWEB_BLOCKS = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/12"

# B17024 bins (ratio of income to poverty line), grouped to match NSCH brackets.
FPL_BINS = {
    "lt100": [3, 4, 5],            # under .50, .50-.74, .75-.99
    "100_199": [6, 7, 8, 9, 10],   # 1.00 - 1.99
    "200_399": [11, 12],           # 2.00 - 3.99
    "400plus": [13, 14],           # 4.00 and over
}
# Column offsets of each age group's "total" row in B17024.
AGE_GROUPS = {"0_5": 2, "6_11": 15, "12_17": 28}


def tracts(cfg: dict) -> gpd.GeoDataFrame:
    y, st = cfg["acs_year"], cfg["state_fips"]
    z = download(TRACT_URL.format(y=y, st=st), raw_dir() / f"cb_{y}_{st}_tract_500k.zip")
    g = gpd.read_file(f"zip://{z}")
    g = g[g["COUNTYFP"].isin(cfg["county_fips"])].to_crs(4326)
    g = g[g["ALAND"] > 0]
    log(f"{len(g):,} tracts")
    return g[["GEOID", "ALAND", "geometry"]].reset_index(drop=True)


def _acs_table(cfg: dict, table: str) -> pd.DataFrame:
    """Stream a national ACS table file and keep only this city's tracts."""
    y, st = cfg["acs_year"], cfg["state_fips"]
    cache = raw_dir(cfg) / f"acs{y}_{table}.csv"
    if not cache.exists():
        prefixes = tuple(f"1400000US{st}{c}" for c in cfg["county_fips"])
        url = ACS_BASE.format(y=y, t=table.lower())
        log(f"streaming ACS {table} ({url})")
        rows, header = [], None
        with get(url, stream=True, timeout=600) as r:
            for raw in r.iter_lines():
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                if header is None:
                    header = line
                elif line.startswith(prefixes):
                    rows.append(line)
        cache.write_text("\n".join([header, *rows]))
    df = pd.read_csv(cache, sep="|", dtype={"GEO_ID": str})
    df["GEOID"] = df["GEO_ID"].str[-11:]
    return df.set_index("GEOID")


def acs(cfg: dict) -> pd.DataFrame:
    pop = _acs_table(cfg, "B01003")
    inc = _acs_table(cfg, "B19013")
    pov = _acs_table(cfg, "B17024")

    def col(n: int) -> pd.Series:
        return pd.to_numeric(pov[f"B17024_E{n:03d}"], errors="coerce").fillna(0)

    out = pd.DataFrame(index=pop.index)
    out["pop"] = pd.to_numeric(pop["B01003_E001"], errors="coerce")
    med = pd.to_numeric(inc["B19013_E001"], errors="coerce")
    out["median_income"] = med.where(med > 0)  # negative values are Census "no data" codes
    for bracket, offsets in FPL_BINS.items():
        # kids 6-17 (NSCH sports question is asked for ages 6-17)
        out[f"kids6_17_{bracket}"] = sum(col(AGE_GROUPS[a] + o - 2) for a in ("6_11", "12_17") for o in offsets)
        out[f"kids0_17_{bracket}"] = out[f"kids6_17_{bracket}"] + sum(col(AGE_GROUPS["0_5"] + o - 2) for o in offsets)
    out["kids0_17"] = sum(col(AGE_GROUPS[a]) for a in AGE_GROUPS)
    out["kids6_17"] = col(AGE_GROUPS["6_11"]) + col(AGE_GROUPS["12_17"])
    out["kids_in_poverty"] = out["kids0_17_lt100"]
    return out.fillna({"pop": 0})


def blocks(cfg: dict) -> gpd.GeoDataFrame:
    """2020 census block populations as points (interior points)."""
    cache = raw_dir(cfg) / "blocks2020.parquet"
    if cache.exists():
        return gpd.read_parquet(cache)
    frames = []
    for county in cfg["county_fips"]:
        log(f"fetching 2020 blocks for county {cfg['state_fips']}{county} from TIGERweb")
        rows = arcgis_query(
            TIGERWEB_BLOCKS,
            where=f"STATE='{cfg['state_fips']}' AND COUNTY='{county}' AND POP100 > 0",
            out_fields="GEOID,POP100,INTPTLAT,INTPTLON",
            geometry=False,
            page_size=20000,
        )
        frames.append(pd.DataFrame(rows))
    df = pd.concat(frames, ignore_index=True)
    g = gpd.GeoDataFrame(
        {"block": df["GEOID"], "tract": df["GEOID"].str[:11], "pop2020": df["POP100"].astype(float)},
        geometry=gpd.points_from_xy(df["INTPTLON"].astype(float), df["INTPTLAT"].astype(float)),
        crs=4326,
    )
    g.to_parquet(cache)
    log(f"{len(g):,} populated blocks, {g['pop2020'].sum():,.0f} people (2020)")
    return g
