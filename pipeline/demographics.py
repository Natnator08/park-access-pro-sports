"""Race/ethnicity, age, and sex from the ACS (tables B03002, B01001, B01002).

Race and ethnicity use the Census's mutually exclusive groups: Hispanic or Latino
of any race, then non-Hispanic people by race. The ACS asks about sex
(male/female), not gender identity, so the site labels it "sex".
"""
from __future__ import annotations

import pandas as pd

# B03002 columns for each group (non-Hispanic unless noted).
RACE = {
    "hispanic": [12],          # Hispanic or Latino, any race
    "white": [3],
    "black": [4],
    "asian": [6],
    "native": [5],             # American Indian and Alaska Native
    "pacific": [7],            # Native Hawaiian and Other Pacific Islander
    "other": [8, 9],           # some other race alone, two or more races
}
RACE_LABELS = {
    "hispanic": "Hispanic or Latino", "white": "White", "black": "Black", "asian": "Asian",
    "native": "Native American", "pacific": "Pacific Islander", "other": "Other or multiracial",
}

# B01001 columns: male 3-25, female 27-49 (same age bands, offset 24).
AGE = {
    "age_0_17": range(3, 7),
    "age_18_34": range(7, 13),
    "age_35_64": range(13, 20),
    "age_65p": range(20, 26),
}
AGE_LABELS = {"age_0_17": "Under 18", "age_18_34": "18–34", "age_35_64": "35–64", "age_65p": "65 and older"}
SEX_LABELS = {"female": "Female", "male": "Male"}

COUNT_COLS = ["race_total", *(f"race_{k}" for k in RACE), "age_total", *AGE, "male", "female"]

# Neighborhood-level shares written to the site (key -> (numerator, denominator)).
SHARES = {
    **{f"pct_{k}": (f"race_{k}", "race_total") for k in RACE},
    **{f"pct_{k.removeprefix('age_')}": (k, "age_total") for k in AGE},
    "pct_female": ("female", "age_total"),
    "pct_male": ("male", "age_total"),
}


def tract_counts(b03002: pd.DataFrame, b01001: pd.DataFrame, b01002: pd.DataFrame) -> pd.DataFrame:
    """Per-tract demographic counts (plus median age) from the three ACS tables."""
    def col(df, table, n):
        return pd.to_numeric(df[f"{table}_E{n:03d}"], errors="coerce").fillna(0)

    out = pd.DataFrame(index=b03002.index.union(b01001.index))
    out["race_total"] = col(b03002, "B03002", 1)
    for k, cols in RACE.items():
        out[f"race_{k}"] = sum(col(b03002, "B03002", c) for c in cols)
    out["age_total"] = col(b01001, "B01001", 1)
    for k, cols in AGE.items():
        out[k] = sum(col(b01001, "B01001", c) + col(b01001, "B01001", c + 24) for c in cols)
    out["male"] = col(b01001, "B01001", 2)
    out["female"] = col(b01001, "B01001", 26)
    med = pd.to_numeric(b01002["B01002_E001"], errors="coerce")
    out["median_age"] = med.where(med > 0)
    return out.fillna(0).assign(median_age=out["median_age"])


def shares(df: pd.DataFrame) -> pd.DataFrame:
    """Add pct_* share columns to a frame holding summed counts."""
    for key, (num, den) in SHARES.items():
        df[key] = (df[num] / df[den]).where(df[den] > 0)
    return df


def composition(df: pd.DataFrame) -> dict:
    """Shares for a whole group of rows (city or income group), for the summary."""
    tot = df[COUNT_COLS].sum()
    race_n, age_n = tot["race_total"], tot["age_total"]
    return {
        "race": {k: round(tot[f"race_{k}"] / race_n, 4) for k in RACE} if race_n else {},
        "age": {k.removeprefix("age_"): round(tot[k] / age_n, 4) for k in AGE} if age_n else {},
        "sex": {"female": round(tot["female"] / age_n, 4), "male": round(tot["male"] / age_n, 4)} if age_n else {},
        "median_age": round(float((df["age_x_pop"].sum() / df["pop_with_age"].sum())), 1)
        if "age_x_pop" in df and df["pop_with_age"].sum() else None,
        "labels": {"race": RACE_LABELS, "age": {k.removeprefix("age_"): v for k, v in AGE_LABELS.items()}, "sex": SEX_LABELS},
    }
