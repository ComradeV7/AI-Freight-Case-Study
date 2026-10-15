import numpy as np
import pandas as pd
import pytest

from src.baselines import add_baselines
from src.load import load_shipments
from src.weekly import build_weekly_costs
from tests.reference_impl import reference_baselines


@pytest.fixture
def weekly():
    shipments = load_shipments()
    return build_weekly_costs(shipments)


@pytest.fixture
def with_baselines(weekly):
    return add_baselines(weekly)


@pytest.fixture
def reference(weekly):
    return reference_baselines(weekly)


def test_total_rows(with_baselines):
    assert len(with_baselines) == 728


def test_history_count(with_baselines):
    assert with_baselines["own_history"].notna().sum() == 721


def test_peer_count(with_baselines):
    assert with_baselines["peer_avg"].notna().sum() == 728


def test_pandas_matches_reference(with_baselines, reference):
    """Pandas and plain-Python implementations agree to 1e-9 on all 728 rows."""
    cols = [
        "cost_per_tonne_km",
        "own_history",
        "n_prior_weeks",
        "peer_avg",
        "pct_vs_history",
        "pct_vs_peers",
    ]

    merged = with_baselines.sort_values(["route", "week_of"]).reset_index(drop=True).merge(
        reference[["route", "week_of"] + cols],
        on=["route", "week_of"],
        suffixes=("", "_ref"),
    )

    for col in cols:
        left = merged[col]
        right = merged[f"{col}_ref"]
        if col == "n_prior_weeks":
            assert (left == right).all(), col
        else:
            diff = (left - right).abs()
            assert diff.max() < 1e-9, f"{col} mismatch: max diff {diff.max()}"


def _row_by_route_week(df, route, week_of_str):
    target = pd.Timestamp(week_of_str)
    row = df[(df["route"] == route) & (df["week_of"] == target)]
    assert len(row) == 1
    return row.iloc[0]


def test_regression_delhi_jaipur_2024_11_11(with_baselines):
    row = _row_by_route_week(with_baselines, "Delhi-Jaipur", "2024-11-11")
    assert round(row["cost_per_tonne_km"], 2) == 4.17
    assert round(row["pct_vs_history"] * 100, 1) == 35.5
    assert round(row["pct_vs_peers"] * 100, 1) == 21.0


def test_regression_ahmedabad_mumbai_2025_01_20(with_baselines):
    row = _row_by_route_week(with_baselines, "Ahmedabad-Mumbai", "2025-01-20")
    assert round(row["cost_per_tonne_km"], 2) == 3.29
    assert round(row["pct_vs_history"] * 100, 1) == 29.5
    assert round(row["pct_vs_peers"] * 100, 1) == 22.5


def test_regression_mumbai_pune_2025_09_15(with_baselines):
    row = _row_by_route_week(with_baselines, "Mumbai-Pune", "2025-09-15")
    assert round(row["cost_per_tonne_km"], 2) == 3.98
    assert round(row["pct_vs_history"] * 100, 1) == 9.2
    assert round(row["pct_vs_peers"] * 100, 1) == 23.6


def test_own_history_excludes_current_week(with_baselines):
    """A row's own_history must never equal its own cost_per_tonne_km."""
    rows_with_history = with_baselines.dropna(subset=["own_history"])
    assert not np.isclose(
        rows_with_history["cost_per_tonne_km"], rows_with_history["own_history"]
    ).any()


def test_first_week_history_is_nan(with_baselines):
    first_weeks = with_baselines.groupby("route")["week_of"].min().reset_index()
    merged = with_baselines.merge(first_weeks, on=["route", "week_of"])
    assert merged["own_history"].isna().all()
    assert (merged["n_prior_weeks"] == 0).all()


def test_peer_avg_excludes_self(with_baselines):
    """peer_avg for a route should differ from the simple route_type-week average when
    the route's own value is not equal to that average."""
    simple_avg = with_baselines.groupby(["route_type", "week_of"])["cost_per_tonne_km"].transform("mean")
    # At least some rows should differ, proving self-exclusion is active.
    assert not np.isclose(with_baselines["peer_avg"], simple_avg).all()
