"""Shared helpers: city config, paths, cached HTTP downloads, ArcGIS paging."""
from __future__ import annotations

import json
import time
from pathlib import Path

import geopandas as gpd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CITIES_DIR = ROOT / "cities"
RAW_DIR = ROOT / "data_raw"
SITE_DATA_DIR = ROOT / "site" / "data"

# A generic client name; no personal contact details are sent to services.
USER_AGENT = "park-access-tracker/0.1 (open data research)"

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


def load_city(slug: str) -> dict:
    path = CITIES_DIR / f"{slug}.yaml"
    if not path.exists():
        raise SystemExit(f"No city config at {path}")
    cfg = yaml.safe_load(path.read_text())
    cfg.setdefault("slug", slug)
    cfg.setdefault("short_name", cfg["name"])
    cfg.setdefault("neighborhoods", {"type": "tracts"})
    cfg["county_fips"] = [str(c).zfill(3) for c in cfg["county_fips"]]
    cfg["state_fips"] = str(cfg["state_fips"]).zfill(2)
    return cfg


def raw_dir(cfg: dict | None = None) -> Path:
    d = RAW_DIR / (cfg["slug"] if cfg else "shared")
    d.mkdir(parents=True, exist_ok=True)
    return d


def log(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def get(url: str, *, params=None, retries: int = 4, timeout: int = 180, **kw) -> requests.Response:
    """GET with retries and exponential backoff."""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except (requests.RequestException, requests.HTTPError) as e:
            if attempt == retries - 1:
                raise
            wait = 5 * 2**attempt
            log(f"retrying in {wait}s after error: {e}")
            time.sleep(wait)
    raise AssertionError("unreachable")


def download(url: str, dest: Path) -> Path:
    """Download url to dest once; later runs reuse the cached file."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    log(f"downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with get(url, stream=True) as r, open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def arcgis_query(layer_url: str, *, where: str = "1=1", bbox=None, out_fields: str = "*",
                 geometry: bool = True, page_size: int = 1000) -> list[dict]:
    """Page through an ArcGIS REST layer query. Returns GeoJSON features
    (geometry=True) or plain attribute dicts (geometry=False)."""
    params = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": str(geometry).lower(),
        "outSR": 4326,
        "f": "geojson" if geometry else "json",
        "resultRecordCount": page_size,
    }
    if bbox:
        params.update({
            "geometry": ",".join(map(str, bbox)),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        })
    out, offset = [], 0
    while True:
        params["resultOffset"] = offset
        data = get(f"{layer_url}/query", params=params).json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS error from {layer_url}: {data['error']}")
        feats = data.get("features", [])
        out.extend(feats if geometry else [f["attributes"] for f in feats])
        exceeded = data.get("exceededTransferLimit") or data.get("properties", {}).get("exceededTransferLimit")
        if not feats or (not exceeded and len(feats) < page_size):
            break
        offset += len(feats)
    return out


def features_to_gdf(features: list[dict]) -> gpd.GeoDataFrame:
    if not features:
        return gpd.GeoDataFrame(geometry=[], crs=4326)
    return gpd.GeoDataFrame.from_features(features, crs=4326)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False))
