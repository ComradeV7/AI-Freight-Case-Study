"""Tests for the stretch-goal Q&A assistant and business insights."""

import hashlib
import re
from pathlib import Path

import pandas as pd
import pytest

from src.business import (
    classify_spike,
    excess_spend,
    inr,
    two_year_drift,
    weekly_with_baselines,
)
from src.load import load_shipments
from src.qa import NO_FINDING, answer, parse_period, resolve_routes


PROJECT_ROOT = Path(__file__).parent.parent
FLAGGED_PATH = PROJECT_ROOT / "outputs" / "flagged_routes.csv"


pytestmark = pytest.mark.skipif(
    not FLAGGED_PATH.exists(),
    reason="outputs/flagged_routes.csv missing; run `python src/main.py` first",
)


# ---------------------------------------------------------------------------
# Q&A assistant (the three briefed prompts + refusals)
# ---------------------------------------------------------------------------
def test_chennai_bangalore_march():
    text = answer("Why did Chennai-Bangalore get pricier in March?")
    assert "N001" in text
    assert "2025-03-03" in text
    assert "2025-03-10" in text and "2025-03-17" in text
    assert "UNEXPLAINED" in text
    # March rows must not be justified by any note other than N001.
    other_notes = set(re.findall(r"N\d{3,}", text)) - {"N001"}
    assert not other_notes, f"unexpected notes cited: {other_notes}"


def test_unknown_route_refused():
    text = answer("why did costs rise on Hyderabad-Bangalore?")
    assert text == NO_FINDING


def test_ahmedabad_mumbai_january():
    text = answer("what happened on Ahmedabad-Mumbai in January 2025?")
    assert "N002" in text
    assert "2025-01-20" in text


def test_no_finding_for_wrong_period():
    # Delhi-Jaipur has no flagged week in February.
    text = answer("why did Delhi-Jaipur get pricier in February?")
    assert text == NO_FINDING


def test_general_summary_without_route():
    text = answer("what did you find?")
    assert "flagged_routes.csv" in text
    for route in ("Chennai-Bangalore", "Mumbai-Pune", "Delhi-Jaipur"):
        assert route in text


def test_qa_does_not_modify_flagged_output():
    before = hashlib.sha256(FLAGGED_PATH.read_bytes()).hexdigest()
    answer("why did Chennai-Bangalore get pricier in March?")
    after = hashlib.sha256(FLAGGED_PATH.read_bytes()).hexdigest()
    assert before == after


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def test_resolve_routes_known_and_unknown():
    assert resolve_routes("why did Mumbai-Pune creep up?") == (["Mumbai-Pune"], False)
    routes, unknown = resolve_routes("what about Hyderabad-Bangalore?")
    assert unknown is True and routes == []


def test_parse_period():
    assert parse_period("Chennai in March 2025") == (3, 2025)
    assert parse_period("anything in Nov") == (11, None)


# ---------------------------------------------------------------------------
# Business compute layer
# ---------------------------------------------------------------------------
def test_inr_indian_grouping():
    assert inr(186423) == "₹1,86,423"
    assert inr(77960) == "₹77,960"
    assert inr(5388) == "₹5,388"


def test_excess_spend_totals_match_known_figures():
    shipments = load_shipments()
    weekly = excess_spend(weekly_with_baselines(shipments))
    lookup = {(r["route"], r["week_of"]): r["excess_inr"] for _, r in weekly.iterrows()}

    justified_weeks = [
        ("Ahmedabad-Mumbai", "2025-01-20"),
        ("Chennai-Bangalore", "2025-02-24"),
        ("Chennai-Bangalore", "2025-03-03"),
    ]
    unexplained_weeks = [
        ("Delhi-Chennai", "2024-02-05"),
        ("Delhi-Jaipur", "2024-11-11"),
        ("Delhi-Jaipur", "2024-11-18"),
        ("Chennai-Bangalore", "2025-03-10"),
        ("Chennai-Bangalore", "2025-03-17"),
        ("Mumbai-Delhi", "2025-05-12"),
        ("Mumbai-Pune", "2025-09-15"),
        ("Mumbai-Pune", "2025-11-17"),
    ]
    just = sum(lookup[(r, pd.Timestamp(w))] for r, w in justified_weeks)
    unexp = sum(lookup[(r, pd.Timestamp(w))] for r, w in unexplained_weeks)
    assert round(just) == 77960
    assert round(unexp) == 108463
    assert round(just + unexp) == 186423


def test_two_year_drift_mumbai_pune_slow_creep():
    shipments = load_shipments()
    drift = {d["route"]: d for d in two_year_drift(weekly_with_baselines(shipments))}
    pune = drift["Mumbai-Pune"]
    assert pune["change_pct"] == pytest.approx(0.286, abs=0.01)
    # The other six routes drifted far less.
    for route, d in drift.items():
        if route != "Mumbai-Pune":
            assert abs(d["change_pct"]) < 0.10


def test_classify_spike():
    corridor = [
        {"transporter": "A", "delta_pct": 0.36},
        {"transporter": "B", "delta_pct": 0.37},
        {"transporter": "C", "delta_pct": 0.33},
    ]
    holdout = [
        {"transporter": "A", "delta_pct": 0.23},
        {"transporter": "B", "delta_pct": 0.21},
        {"transporter": "C", "delta_pct": 0.02},
        {"transporter": "D", "delta_pct": 0.03},
    ]
    assert classify_spike(corridor) == "corridor-wide"
    assert classify_spike(holdout) == "vendor-holdout"
    assert classify_spike([{"transporter": "A", "delta_pct": 0.2}]) == "single-vendor"


# ---------------------------------------------------------------------------
# Insights report
# ---------------------------------------------------------------------------
def test_build_report_smoke(tmp_path):
    from src.insights import build_report

    report = build_report()
    assert "Financial impact triage" in report
    assert "₹77,960" in report
    assert "₹1,08,463" in report
    assert "₹1,86,423" in report
    assert "Mumbai-Pune" in report and "28.6%" in report
    assert "8-column" in report
