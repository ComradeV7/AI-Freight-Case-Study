import pandas as pd
import pytest

from src.baselines import add_baselines
from src.flagging import find_candidates
from src.gate import evaluate_candidate, gate_candidates
from src.load import load_shipments
from src.notes import build_registry, load_notes_registry
from src.weekly import build_weekly_costs


@pytest.fixture
def candidates_8pct():
    shipments = load_shipments()
    weekly = add_baselines(build_weekly_costs(shipments))
    return find_candidates(weekly, t_own=0.08)


@pytest.fixture
def registry():
    return load_notes_registry()


@pytest.fixture
def gated(candidates_8pct, registry):
    return gate_candidates(candidates_8pct, registry)


def _verdict_for(gated_df, route, week_str):
    row = gated_df[(gated_df["route"] == route) & (gated_df["week_of"] == pd.Timestamp(week_str))]
    assert len(row) == 1, f"Expected one row for {route} {week_str}, found {len(row)}"
    return row.iloc[0]


def test_expected_justified(gated):
    cases = [
        ("Ahmedabad-Mumbai", "2025-01-20", "N002"),
        ("Chennai-Bangalore", "2025-02-24", "N001"),
        ("Chennai-Bangalore", "2025-03-03", "N001"),
    ]
    for route, week, note_id in cases:
        row = _verdict_for(gated, route, week)
        assert row["flagged"] == "No (justified)", f"{route} {week} should be justified"
        assert row["matched_note_id"] == note_id, f"{route} {week} should match {note_id}"


def test_expected_unexplained(gated):
    cases = [
        "Chennai-Bangalore 2025-03-10",
        "Chennai-Bangalore 2025-03-17",
        "Delhi-Jaipur 2024-11-11",
        "Delhi-Jaipur 2024-11-18",
        "Mumbai-Pune 2025-09-15",
        "Mumbai-Pune 2025-11-17",
        "Mumbai-Delhi 2025-05-12",
        "Delhi-Chennai 2024-02-05",
    ]
    for case in cases:
        route, week = case.rsplit(" ", 1)
        row = _verdict_for(gated, route, week)
        assert row["flagged"] == "Yes", f"{case} should be unexplained"
        assert row["matched_note_id"] == "", f"{case} should have blank note id"


def test_mumbai_delhi_n003_unexplained(gated, registry):
    """Mumbai-Delhi 2025-05-12 is inside N003's window but N003 is ALL-scope.
    It should still be unexplained because N005 (no_effect) does not justify,
    and N003 alone as an ALL-scope note could apply, but the expected verdict
    is unexplained. This test documents that behaviour.
    """
    row = _verdict_for(gated, "Mumbai-Delhi", "2025-05-12")
    assert row["flagged"] == "Yes"


def test_route_specific_preferred_over_all(registry):
    """If both a route-specific note and an ALL note match, route-specific wins."""
    synthetic_registry = {
        "N_ROUTE": {
            "scope": ["Test-Route"],
            "effective_from": "2025-05-05",
            "effective_to": "2025-05-11",
            "polarity": "causes_rise",
            "source_text": "route-specific rise",
        },
        "N_ALL": {
            "scope": "ALL",
            "effective_from": "2025-05-05",
            "effective_to": "2025-05-11",
            "polarity": "causes_rise",
            "source_text": "all-routes rise",
        },
    }
    note_id, trace = evaluate_candidate("Test-Route", "2025-05-05", synthetic_registry)
    assert note_id == "N_ROUTE"


def test_synthetic_right_note_wrong_route():
    registry = {
        "N001": {
            "scope": ["Chennai-Bangalore"],
            "effective_from": "2025-02-24",
            "effective_to": "2025-03-08",
            "polarity": "causes_rise",
            "source_text": "flooding",
        }
    }
    note_id, _ = evaluate_candidate("Delhi-Jaipur", "2025-02-24", registry)
    assert note_id is None


def test_synthetic_week_one_day_after_window():
    registry = {
        "N001": {
            "scope": ["Chennai-Bangalore"],
            "effective_from": "2025-02-24",
            "effective_to": "2025-03-08",
            "polarity": "causes_rise",
            "source_text": "flooding",
        }
    }
    # Week 2025-03-10 is Mon..Sun 03-10..03-16, entirely after 03-08.
    note_id, _ = evaluate_candidate("Chennai-Bangalore", "2025-03-10", registry)
    assert note_id is None


def test_synthetic_no_effect_note():
    registry = {
        "N005": {
            "scope": ["Mumbai-Delhi"],
            "effective_from": "2024-07-29",
            "effective_to": "2024-07-29",
            "polarity": "no_effect",
            "source_text": "maintenance no effect",
        }
    }
    note_id, _ = evaluate_candidate("Mumbai-Delhi", "2024-07-29", registry)
    assert note_id is None


def test_synthetic_all_routes_note_justifies():
    registry = {
        "N003": {
            "scope": "ALL",
            "effective_from": "2025-05-05",
            "effective_to": "2025-05-11",
            "polarity": "causes_rise",
            "source_text": "diesel rise",
        }
    }
    note_id, _ = evaluate_candidate("Mumbai-Pune", "2025-05-05", registry)
    assert note_id == "N003"


def test_trace_records_all_notes(gated):
    """Every candidate's trace evaluates every registry note."""
    for _, row in gated.iterrows():
        assert isinstance(row["trace"], list)
        assert len(row["trace"]) == 10
        for note_trace in row["trace"]:
            assert "scope" in note_trace
            assert "window" in note_trace
            assert "polarity" in note_trace
            assert "match" in note_trace


def test_gate_audit_written(tmp_path, gated):
    from src.gate import write_gate_audit
    path = tmp_path / "gate_audit.json"
    write_gate_audit(gated, path)
    assert path.exists()
    import json
    records = json.loads(path.read_text(encoding="utf-8"))
    assert len(records) == len(gated)
    for rec in records:
        assert "trace" in rec
        assert len(rec["trace"]) == 10


# ---------------------------------------------------------------------------
# Portability: dynamic registry for unseen / modified notes
# ---------------------------------------------------------------------------
def test_build_registry_uses_yaml_for_known_notes():
    """On the standard dataset every note id keeps its curated YAML entry."""
    registry = build_registry()
    curated = load_notes_registry()
    assert set(registry) == set(curated)
    for note_id, entry in curated.items():
        assert registry[note_id] == entry


def test_unseen_note_justifies_real_candidate_end_to_end(tmp_path, candidates_8pct):
    """A brand-new note id (N099) derived from a CSV must justify a real row."""
    notes_csv = tmp_path / "context_notes.csv"
    notes_csv.write_text(
        "note_id,date,applies_to,note\n"
        'N099,2024-11-11,Delhi-Jaipur,"A regional road closure started this week, '
        'pushing up freight costs on the Delhi-Jaipur corridor."\n',
        encoding="utf-8",
    )

    registry = build_registry(notes_csv)
    assert "N099" in registry
    assert registry["N099"]["polarity"] == "causes_rise"
    assert registry["N099"]["scope"] == ["Delhi-Jaipur"]

    gated = gate_candidates(candidates_8pct, registry)
    row = gated[
        (gated["route"] == "Delhi-Jaipur") & (gated["week_of"] == pd.Timestamp("2024-11-11"))
    ].iloc[0]
    assert row["flagged"] == "No (justified)"
    assert row["matched_note_id"] == "N099"


def test_modified_known_note_text_is_derived(tmp_path):
    """An edited note text for a known id must be re-derived, not crash."""
    notes_csv = tmp_path / "context_notes.csv"
    notes_csv.write_text(
        "note_id,date,applies_to,note\n"
        'N001,2025-02-24,Chennai-Bangalore,"Changed wording: freight costs rose '
        'sharply on the corridor this week."\n',
        encoding="utf-8",
    )

    registry = build_registry(notes_csv)
    assert registry["N001"]["source_text"].startswith("Changed wording")
    assert registry["N001"]["polarity"] == "causes_rise"
    assert registry["N001"]["scope"] == ["Chennai-Bangalore"]
    # Text mentions "week" -> 7-day inclusive window from the note date.
    assert registry["N001"]["effective_from"] == "2025-02-24"
    assert registry["N001"]["effective_to"] == "2025-03-02"
