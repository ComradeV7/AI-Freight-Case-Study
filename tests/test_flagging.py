import pandas as pd
import pytest

from src.baselines import add_baselines
from src.flagging import (
    build_sensitivity_report,
    find_candidates,
    load_params,
)
from src.load import load_shipments
from src.weekly import build_weekly_costs


@pytest.fixture
def weekly():
    shipments = load_shipments()
    return add_baselines(build_weekly_costs(shipments))


def test_load_params():
    params = load_params()
    assert params["flagging"]["t_own"] == 0.08
    assert params["flagging"]["t_peer"] == 0.15


def test_candidates_at_8_percent(weekly):
    candidates = find_candidates(weekly, t_own=0.08)
    assert len(candidates) == 11

    keys = set(
        candidates.apply(lambda r: f"{r['route']} {r['week_of'].strftime('%Y-%m-%d')}", axis=1)
    )
    expected = {
        "Ahmedabad-Mumbai 2025-01-20",
        "Chennai-Bangalore 2025-02-24",
        "Chennai-Bangalore 2025-03-03",
        "Chennai-Bangalore 2025-03-10",
        "Chennai-Bangalore 2025-03-17",
        "Delhi-Chennai 2024-02-05",
        "Delhi-Jaipur 2024-11-11",
        "Delhi-Jaipur 2024-11-18",
        "Mumbai-Delhi 2025-05-12",
        "Mumbai-Pune 2025-09-15",
        "Mumbai-Pune 2025-11-17",
    }
    assert keys == expected


def test_candidates_are_rising(weekly):
    candidates = find_candidates(weekly, t_own=0.08)
    assert (candidates["pct_vs_history"] > 0).all()
    assert (candidates["pct_vs_history"] >= 0.08).all()


def test_candidates_excludes_current_week(weekly):
    candidates = find_candidates(weekly, t_own=0.08)
    for _, row in candidates.iterrows():
        route_weeks = weekly[
            (weekly["route"] == row["route"]) & (weekly["week_of"] < row["week_of"])
        ].sort_values("week_of")
        assert len(route_weeks) >= 1 or row["route"] == "Delhi-Chennai"


def test_sensitivity_report_shape(weekly):
    base = find_candidates(weekly, t_own=0.08)
    report = build_sensitivity_report(base, weekly)
    assert len(report) == 5
    assert set(report["variant"]) == {
        "T_own=5%",
        "T_own=8%",
        "T_own=10%",
        "T_own=15%",
        "T_own=8% OR peer>=15%",
    }


def test_sensitivity_report_default_has_no_added_or_removed(weekly):
    base = find_candidates(weekly, t_own=0.08)
    report = build_sensitivity_report(base, weekly)
    default = report[report["variant"] == "T_own=8%"].iloc[0]
    assert default["candidate_count"] == 11
    assert default["added_count"] == 0
    assert default["removed_count"] == 0


def test_peer_variant_adds_candidates(weekly):
    base = find_candidates(weekly, t_own=0.08)
    peer_variant = find_candidates(weekly, t_own=0.08, use_peers=True, t_peer=0.15)
    assert len(peer_variant) > len(base)
    assert len(peer_variant) == 28
