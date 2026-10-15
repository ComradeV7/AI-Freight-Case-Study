import numpy as np
import pandas as pd
from src.load import load_shipments
from src.weekly import build_weekly_costs


def reference_baselines(weekly: pd.DataFrame, window: int = 8) -> pd.DataFrame:
    """Plain-Python reference implementation of the baseline logic."""
    df = weekly.sort_values(["route", "week_of"]).copy()
    rows = df.to_dict("records")

    # Own history: per-route list of weekly values in chronological order.
    route_weeks: dict[str, list[dict]] = {}
    for row in rows:
        route_weeks.setdefault(row["route"], []).append(row)

    for route, weeks in route_weeks.items():
        for i, row in enumerate(weeks):
            if i == 0:
                row["own_history"] = np.nan
                row["n_prior_weeks"] = 0
            else:
                start = max(0, i - window)
                prior = [w["cost_per_tonne_km"] for w in weeks[start:i]]
                row["own_history"] = sum(prior) / len(prior)
                row["n_prior_weeks"] = len(prior)

    # Peer average: same route_type and week, excluding the route itself.
    type_week_groups: dict[tuple[str, pd.Timestamp], list[dict]] = {}
    for row in rows:
        key = (row["route_type"], row["week_of"])
        type_week_groups.setdefault(key, []).append(row)

    for group in type_week_groups.values():
        for row in group:
            others = [r["cost_per_tonne_km"] for r in group if r["route"] != row["route"]]
            row["peer_avg"] = sum(others) / len(others)

    # Percentage differences.
    for row in rows:
        if pd.isna(row["own_history"]):
            row["pct_vs_history"] = np.nan
        else:
            row["pct_vs_history"] = (row["cost_per_tonne_km"] - row["own_history"]) / row["own_history"]
        row["pct_vs_peers"] = (row["cost_per_tonne_km"] - row["peer_avg"]) / row["peer_avg"]

    result = pd.DataFrame(rows)
    result = result.sort_values(["route", "week_of"]).reset_index(drop=True)
    return result


def compute_reference() -> pd.DataFrame:
    """Convenience helper: load, aggregate, and compute reference baselines."""
    shipments = load_shipments()
    weekly = build_weekly_costs(shipments)
    return reference_baselines(weekly)


if __name__ == "__main__":
    ref = compute_reference()
    print(ref.head())
    print(f"Rows: {len(ref)}")
    print(f"Rows with history: {ref['own_history'].notna().sum()}")
    print(f"Rows with peers: {ref['peer_avg'].notna().sum()}")
