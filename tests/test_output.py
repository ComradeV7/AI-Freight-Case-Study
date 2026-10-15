import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
import pytest

from src.baselines import add_baselines
from src.flagging import find_candidates, load_params
from src.gate import gate_candidates
from src.load import load_shipments
from src.output import (
    FLAGGED_PATH,
    GRID_PATH,
    build_all_weeks_grid,
    format_flagged_output,
    write_all_weeks_grid,
    write_flagged_routes,
)
from src.weekly import build_weekly_costs


@pytest.fixture
def sample_header():
    sample_path = Path(__file__).parent.parent / "data" / "sample_output_format_v2.csv"
    with open(sample_path, "r", encoding="utf-8") as f:
        header_line = f.readline().strip()
    return header_line.split(",")


@pytest.fixture
def flagged_output():
    shipments = load_shipments()
    weekly = add_baselines(build_weekly_costs(shipments))
    params = load_params()
    candidates = find_candidates(weekly, t_own=params["flagging"]["t_own"])
    gated = gate_candidates(candidates)
    return format_flagged_output(gated)


@pytest.fixture
def all_weeks_grid():
    shipments = load_shipments()
    weekly = add_baselines(build_weekly_costs(shipments))
    return build_all_weeks_grid(weekly)


def test_header_matches_sample(flagged_output, sample_header):
    assert list(flagged_output.columns) == sample_header


def test_all_dates_iso(flagged_output):
    assert flagged_output["week_of"].apply(lambda x: bool(re.match(r"^\d{4}-\d{2}-\d{2}$", x))).all()


def test_no_nan_text(flagged_output):
    for col in flagged_output.columns:
        assert not flagged_output[col].astype(str).str.lower().isin(["nan", "none", "null"]).any()


def test_justified_rows_have_note_id(flagged_output):
    justified = flagged_output[flagged_output["flagged"] == "No (justified)"]
    assert (justified["matched_note_id"].str.len() > 0).all()


def test_yes_rows_have_blank_note_id(flagged_output):
    yes_rows = flagged_output[flagged_output["flagged"] == "Yes"]
    assert (yes_rows["matched_note_id"] == "").all()


def test_flagged_values_valid(flagged_output):
    assert set(flagged_output["flagged"].unique()).issubset({"Yes", "No (justified)"})


def test_cost_two_decimals(flagged_output):
    for value in flagged_output["cost_per_tonne_km"]:
        assert re.match(r"^\d+\.\d{2}$", value)


def test_vs_history_format(flagged_output):
    pattern = re.compile(r"^[+-]\d+\.\d% vs this route's past average$")
    assert flagged_output["vs_own_history"].apply(lambda x: bool(pattern.match(x))).all()


def test_vs_peers_format(flagged_output):
    pattern = re.compile(r"^[+-]\d+\.\d% vs similar-length routes this week$")
    assert flagged_output["vs_similar_routes"].apply(lambda x: bool(pattern.match(x))).all()


def _round_decimal(value, places):
    d = Decimal(str(value)).quantize(Decimal("0." + "0" * places), rounding=ROUND_HALF_UP)
    return f"{d:.{places}f}"


def _format_pct_decimal(value):
    d = Decimal(str(value * 100.0)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    sign = "+" if d >= 0 else "-"
    return f"{sign}{abs(d):.1f}"


def _find_row(df, route, week):
    row = df[(df["route"] == route) & (df["week_of"] == week)]
    assert len(row) == 1, f"Expected one row for {route} {week}"
    return row.iloc[0]


def test_sample_rows_match_expected(flagged_output):
    cases = [
        ("Delhi-Jaipur", "2024-11-11", 4.17, 0.355, 0.210),
        ("Ahmedabad-Mumbai", "2025-01-20", 3.29, 0.295, 0.225),
        ("Mumbai-Pune", "2025-09-15", 3.98, 0.092, 0.236),
    ]
    for route, week, cost, hist, peer in cases:
        row = _find_row(flagged_output, route, week)
        assert row["cost_per_tonne_km"] == _round_decimal(cost, 2)
        assert row["vs_own_history"] == f"{_format_pct_decimal(hist)}% vs this route's past average"
        assert row["vs_similar_routes"] == f"{_format_pct_decimal(peer)}% vs similar-length routes this week"


def test_sorted_by_week_then_route(flagged_output):
    sorted_df = flagged_output.sort_values(["week_of", "route"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(flagged_output.reset_index(drop=True), sorted_df)


def test_all_weeks_grid_shape(all_weeks_grid):
    assert len(all_weeks_grid) == 728


def test_all_weeks_grid_no_nan(all_weeks_grid):
    # cost and peer averages exist for every route-week.
    assert all_weeks_grid["cost_per_tonne_km"].notna().all()
    assert all_weeks_grid["vs_similar_routes"].notna().all()
    # own-history is NaN only for a route's first week (7 rows total).
    assert all_weeks_grid["vs_own_history"].isna().sum() == 7


def test_all_weeks_grid_numeric_types(all_weeks_grid):
    assert pd.api.types.is_float_dtype(all_weeks_grid["cost_per_tonne_km"])
    assert pd.api.types.is_float_dtype(all_weeks_grid["vs_own_history"])
    assert pd.api.types.is_float_dtype(all_weeks_grid["vs_similar_routes"])


def test_write_outputs(tmp_path, flagged_output, all_weeks_grid):
    flagged_path = tmp_path / "flagged_routes.csv"
    grid_path = tmp_path / "all_weeks_grid.csv"
    write_flagged_routes(flagged_output, flagged_path)
    write_all_weeks_grid(all_weeks_grid, grid_path)

    assert flagged_path.exists()
    assert grid_path.exists()

    # Verify LF line endings.
    flagged_text = flagged_path.read_bytes()
    assert b"\r\n" not in flagged_text
    grid_text = grid_path.read_bytes()
    assert b"\r\n" not in grid_text

    # Verify header equality with the sample file.
    written = pd.read_csv(flagged_path)
    sample_path = Path(__file__).parent.parent / "data" / "sample_output_format_v2.csv"
    with open(sample_path, "r", encoding="utf-8") as f:
        sample_header = f.readline().strip().split(",")
    assert list(written.columns) == sample_header
