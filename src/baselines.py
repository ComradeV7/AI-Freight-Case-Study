import numpy as np
import pandas as pd


HISTORY_WINDOW = 8


def add_own_history(weekly: pd.DataFrame, window: int = HISTORY_WINDOW) -> pd.DataFrame:
    """Mean of the previous up-to-`window` weekly cost values for the same route."""
    df = weekly.sort_values(["route", "week_of"]).copy()

    df["own_history"] = df.groupby("route", group_keys=False)["cost_per_tonne_km"].apply(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).mean()
    )
    df["n_prior_weeks"] = df.groupby("route", group_keys=False)["cost_per_tonne_km"].apply(
        lambda s: s.shift(1).rolling(window=window, min_periods=1).count()
    )

    return df


def add_peer_avg(weekly: pd.DataFrame) -> pd.DataFrame:
    """Unweighted mean of the OTHER routes' weekly values in the same route_type and week."""
    df = weekly.copy()
    stats = (
        df.groupby(["route_type", "week_of"], as_index=False)
        .agg(peer_sum=("cost_per_tonne_km", "sum"), peer_count=("cost_per_tonne_km", "count"))
    )
    df = df.merge(stats, on=["route_type", "week_of"])
    df["peer_avg"] = (df["peer_sum"] - df["cost_per_tonne_km"]) / (df["peer_count"] - 1)
    df = df.drop(columns=["peer_sum", "peer_count"])
    return df


def add_baselines(weekly: pd.DataFrame, window: int = HISTORY_WINDOW) -> pd.DataFrame:
    """Add own-history, peer-average and percentage-difference columns."""
    df = add_own_history(weekly, window=window)
    df = add_peer_avg(df)

    df["pct_vs_history"] = (df["cost_per_tonne_km"] - df["own_history"]) / df["own_history"]
    df["pct_vs_peers"] = (df["cost_per_tonne_km"] - df["peer_avg"]) / df["peer_avg"]

    return df
