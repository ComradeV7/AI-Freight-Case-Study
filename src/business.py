"""Business analytics over shipment data (shared compute layer).

Pure functions (no file writes) used by ``src/insights.py`` (executive report)
and ``src/qa.py`` (stretch-goal Q&A).  Everything is derived from
``data/shipment_records.csv`` and the exact 8-week baseline definitions in
``src/baselines.py``; nothing here mutates ``outputs/flagged_routes.csv``.

Three analytics:
  1. Excess spend vs the trailing 8-week baseline (INR).
  2. Transporter-level drilldown (corridor-wide spike vs single-vendor holdout).
  3. Two-year drift (first 8w of 2024 vs last 8w of 2025) per route.
"""

import re
import sys
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.baselines import HISTORY_WINDOW, add_baselines
from src.weekly import build_weekly_costs


# Classification thresholds (fractions).
CORRIDOR_WIDE_MIN_DELTA = 0.08   # every active transporter above this -> corridor-wide
HOLDOUT_SPREAD_PP = 0.10         # within-week spread above this -> split/holdout
HOLDOUT_MIN_DELTA = 0.08         # at least one transporter below this -> holdout


def inr(value: float) -> str:
    """Format an amount with Indian digit grouping, e.g. 186423 -> '₹1,86,423'."""
    negative = value < 0
    digits = f"{abs(int(round(value))):d}"
    if len(digits) > 3:
        last3 = digits[-3:]
        rest = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", digits[:-3])
        digits = f"{rest},{last3}"
    return f"{'-' if negative else ''}₹{digits}"


def weekly_with_baselines(shipments: pd.DataFrame) -> pd.DataFrame:
    """Weekly pooled cost-per-tonne-km plus own-history/peer baselines."""
    return add_baselines(build_weekly_costs(shipments))


def excess_spend(weekly: pd.DataFrame) -> pd.DataFrame:
    """Add ``excess_inr = total_cost - own_history * total_tonne_km`` per route-week.

    Positive = spend above the route's trailing 8-week baseline.  NaN in a
    route's first week (no prior history) is expected.
    """
    df = weekly.copy()
    df["excess_inr"] = df["total_cost"] - df["own_history"] * df["total_tonne_km"]
    return df


def transporter_weekly(shipments: pd.DataFrame, route: str) -> pd.DataFrame:
    """Per-transporter weekly cost-per-tonne-km on a route + trailing 8-week mean."""
    s = shipments[shipments["route"] == route].copy()
    s["tonne_km"] = s["quantity_tonnes"] * s["distance_km"]

    t = (
        s.groupby(["transporter", "week_of"], as_index=False)
        .agg(total_cost=("freight_cost_inr", "sum"), total_tonne_km=("tonne_km", "sum"))
    )
    t["cost_per_tonne_km"] = t["total_cost"] / t["total_tonne_km"]
    t = t.sort_values(["transporter", "week_of"])
    t["trailing8"] = t.groupby("transporter")["cost_per_tonne_km"].transform(
        lambda x: x.shift(1).rolling(HISTORY_WINDOW, min_periods=1).mean()
    )
    t["delta_pct"] = (t["cost_per_tonne_km"] - t["trailing8"]) / t["trailing8"]
    return t


def transporter_drilldown(
    shipments: pd.DataFrame, route: str, week_of
) -> list[dict]:
    """Per-transporter stats for one route-week (delta vs trailing 8-week mean)."""
    t = transporter_weekly(shipments, route)
    week_of = pd.Timestamp(week_of)
    rows = t[t["week_of"] == week_of].sort_values("transporter")
    out = []
    for _, r in rows.iterrows():
        out.append(
            {
                "transporter": r["transporter"],
                "cost_per_tonne_km": float(r["cost_per_tonne_km"]),
                "trailing8": float(r["trailing8"]) if pd.notna(r["trailing8"]) else None,
                "delta_pct": float(r["delta_pct"]) if pd.notna(r["delta_pct"]) else None,
            }
        )
    return out


def classify_spike(rows: list[dict]) -> str:
    """Classify a week's transporter deltas.

    * ``corridor-wide``  - every active transporter is up > CORRIDOR_WIDE_MIN_DELTA
    * ``vendor-holdout`` - spread > HOLDOUT_SPREAD_PP and at least one transporter
                           is below HOLDOUT_MIN_DELTA (some normalised, others didn't)
    * ``single-vendor``  - only one transporter active
    * ``mixed``          - otherwise
    * ``insufficient-data`` - no deltas available
    """
    deltas = [r["delta_pct"] for r in rows if r.get("delta_pct") is not None]
    if not deltas:
        return "insufficient-data"
    if len(deltas) == 1:
        return "single-vendor"
    low, high = min(deltas), max(deltas)
    if low > CORRIDOR_WIDE_MIN_DELTA:
        return "corridor-wide"
    if (high - low) > HOLDOUT_SPREAD_PP and low < HOLDOUT_MIN_DELTA:
        return "vendor-holdout"
    return "mixed"


def two_year_drift(weekly: pd.DataFrame) -> list[dict]:
    """First 8 weeks of 2024 vs last 8 weeks of 2025, per route."""
    out = []
    for route in sorted(weekly["route"].unique()):
        w = weekly[weekly["route"] == route]
        start = w[w["week_of"].dt.year == 2024].sort_values("week_of").head(8)
        end = w[w["week_of"].dt.year == 2025].sort_values("week_of").tail(8)
        if start.empty or end.empty:
            continue
        a = float(start["cost_per_tonne_km"].mean())
        b = float(end["cost_per_tonne_km"].mean())
        out.append(
            {
                "route": route,
                "start_2024": a,
                "end_2025": b,
                "change_pct": (b / a - 1.0) if a else 0.0,
            }
        )
    return out
