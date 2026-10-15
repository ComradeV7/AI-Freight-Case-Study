from pathlib import Path

import pandas as pd
import pytest

from eval.audit_justified import audit_justified_rows, extract_window_from_text, note_describes_cost_rise, route_matches
from eval.generate_report import _run_retrieval_ablation
from eval.mutation_tests import run_mutations
from eval.run_eval import compute_metrics, load_labeled_and_output


@pytest.fixture
def labeled_and_output():
    return load_labeled_and_output()


def test_verdict_accuracy_perfect(labeled_and_output):
    labeled, output = labeled_and_output
    metrics = compute_metrics(labeled, output)
    assert metrics["verdict_accuracy"] == 1.0


def test_cited_note_accuracy_perfect(labeled_and_output):
    labeled, output = labeled_and_output
    metrics = compute_metrics(labeled, output)
    assert metrics["cited_note_accuracy"] == 1.0


def test_fabrication_count_zero(labeled_and_output):
    labeled, output = labeled_and_output
    metrics = compute_metrics(labeled, output)
    assert metrics["fabrication_count"] == 0


def test_sample_numeric_fields_match(labeled_and_output):
    labeled, output = labeled_and_output
    metrics = compute_metrics(labeled, output)
    assert metrics["sample_match_rate"] == 1.0


def test_audit_all_justified_pass():
    findings = audit_justified_rows()
    assert all(f["passed"] for f in findings)


def test_route_matches_all_routes():
    row = pd.Series({"applies_to": "All Routes", "note": "x"})
    assert route_matches(row, "Any-Route")


def test_route_matches_specific():
    row = pd.Series({"applies_to": "Chennai-Bangalore", "note": "x"})
    assert route_matches(row, "Chennai-Bangalore")
    assert not route_matches(row, "Delhi-Jaipur")


def test_note_describes_cost_rise():
    assert note_describes_cost_rise("Diesel prices rose, pushing up costs.")
    assert note_describes_cost_rise("A temporary surcharge was applied.")
    assert not note_describes_cost_rise("No significant disruptions reported.")


def test_extract_window_from_text_range():
    text = "Heavy flooding from Feb 24 to Mar 8 disrupted movement."
    start, end = extract_window_from_text(text, pd.Timestamp("2025-02-24"))
    assert start == pd.Timestamp("2025-02-24")
    assert end == pd.Timestamp("2025-03-08")


def test_extract_window_from_text_week():
    text = "A regional festival week saw a surcharge."
    start, end = extract_window_from_text(text, pd.Timestamp("2025-01-20"))
    assert start == pd.Timestamp("2025-01-20")
    assert end == pd.Timestamp("2025-01-26")


def test_mutation_tests_all_flip():
    results = run_mutations()
    assert all(r["flipped_to_unexplained"] for r in results)


def test_retrieval_ablation_shows_wrong_window_trap():
    results = _run_retrieval_ablation()
    assert len(results) >= 1
    for r in results:
        assert r["gate_verdict"] == "Yes"
        assert r["expected_note_still_in_top3"] is True


def test_labeled_file_exists():
    path = Path(__file__).parent.parent / "eval" / "labeled.csv"
    assert path.exists()
    df = pd.read_csv(path)
    assert set(df.columns) == {"route", "week_of", "expected_flag", "expected_note_id"}
    assert len(df) == 11
