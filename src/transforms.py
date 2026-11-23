"""
Transformations applied to a raw (date, value) series.

Every transformation adds ONE derived column next to the untouched source
`value`, so the CSV always keeps the number exactly as the source published it
(that is what verify/check.py compares against).
"""

from __future__ import annotations

import pandas as pd


def yoy_pct(df: pd.DataFrame) -> pd.DataFrame:
    """Year-over-year % change for monthly data.

    yoy_pct_t = 100 * (value_t / value_{t-12 months} - 1)

    Matched by calendar date (same month one year earlier), not by row
    position, so a missing month at the source gives a blank instead of
    silently comparing against the wrong month.
    """
    prior = df[["date", "value"]].copy()
    prior["date"] = prior["date"] + pd.DateOffset(years=1)  # shift last year's value forward
    prior = prior.rename(columns={"value": "value_12m_ago"})
    out = df.merge(prior, on="date", how="left")
    out["yoy_pct"] = 100.0 * (out["value"] / out["value_12m_ago"] - 1.0)
    return out.drop(columns="value_12m_ago")


def none(df: pd.DataFrame) -> pd.DataFrame:
    """No transformation: the chart draws the source value as published."""
    return df


TRANSFORMS = {"none": none, "yoy_pct": yoy_pct}

# Name of the derived column each transform creates (None = no derived column).
DERIVED_COLUMN = {"none": None, "yoy_pct": "yoy_pct"}
