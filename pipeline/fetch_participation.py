"""Youth organized-sports participation by household income, from the
National Survey of Children's Health (NSCH) public-use microdata.

Question K7Q30 (asked for ages 6-17): "During the past 12 months, did this
child participate in a sports team or take sports lessons after school or on
weekends?"  1 = Yes, 2 = No.  FPL_I1 = family income as % of the federal
poverty line (imputed, top-coded at 400).  FWC = survey weight.
"""
from __future__ import annotations

import zipfile

import numpy as np
import pandas as pd

from common import download, log, raw_dir

NSCH_URL = "https://www2.census.gov/programs-surveys/nsch/datasets/{y}/nsch_{y}_topical_Stata.zip"
BRACKETS = ["lt100", "100_199", "200_399", "400plus"]
BRACKET_LABELS = {"lt100": "Below poverty line", "100_199": "100–199% of poverty line",
                  "200_399": "200–399% of poverty line", "400plus": "400%+ of poverty line"}
MIN_STATE_N = 150  # below this, fall back to the national rate for a bracket


def _load_year(y: int) -> pd.DataFrame:
    z = download(NSCH_URL.format(y=y), raw_dir() / "nsch" / f"nsch_{y}_topical_Stata.zip")
    with zipfile.ZipFile(z) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".dta"))
        with zf.open(name) as f:
            df = pd.read_stata(f, columns=["fipsst", "sc_age_years", "k7q30", "fpl_i1", "fwc"],
                               convert_categoricals=False)
    df["year"] = y
    return df


def _rate(d: pd.DataFrame) -> dict:
    w = d["fwc"].to_numpy()
    yes = (d["k7q30"] == 1).to_numpy()
    p = float(np.average(yes, weights=w))
    n_eff = w.sum() ** 2 / (w**2).sum()  # Kish effective sample size
    se = (p * (1 - p) / n_eff) ** 0.5
    return {"rate": round(p, 4), "ci95": [round(p - 1.96 * se, 4), round(p + 1.96 * se, 4)], "n": int(len(d))}


def participation_rates(cfg: dict) -> dict:
    pcfg = cfg["participation"]
    years = pcfg["nsch_years"]
    df = pd.concat([_load_year(y) for y in years], ignore_index=True)
    df = df[(df["sc_age_years"] >= 6) & df["k7q30"].isin([1, 2]) & (df["fwc"] > 0)]
    df["bracket"] = pd.cut(df["fpl_i1"], [0, 99.5, 199.5, 399.5, 10_000], labels=BRACKETS)
    state = df[df["fipsst"].astype(int) == int(pcfg["state_fips"])]

    out = {"years": years, "state_fips": pcfg["state_fips"], "brackets": {}}
    for b in BRACKETS:
        s, nat = state[state["bracket"] == b], df[df["bracket"] == b]
        use_state = len(s) >= MIN_STATE_N
        r = _rate(s if use_state else nat)
        r.update(label=BRACKET_LABELS[b], scope="state" if use_state else "national",
                 national_rate=_rate(nat)["rate"])
        out["brackets"][b] = r
    out["state_overall"] = _rate(state)
    out["national_overall"] = _rate(df)
    log("participation by income: " + ", ".join(f"{b} {out['brackets'][b]['rate']:.0%}" for b in BRACKETS))
    return out
