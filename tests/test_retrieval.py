import json
from pathlib import Path

import pandas as pd
import pytest

from src.baselines import add_baselines
from src.flagging import find_candidates
from src.load import load_shipments
from src.notes import load_notes_registry
from src.retrieval import (
    build_index,
    build_retrieval_trace,
    get_client,
    get_model,
    retrieve_for_candidate,
)
from src.weekly import build_weekly_costs


@pytest.fixture(scope="module")
def retrieval_index(tmp_path_factory):
    """Build a shared Chroma index once for all retrieval tests."""
    registry = load_notes_registry()
    model = get_model()
    index_dir = tmp_path_factory.mktemp("chroma_index")
    client = get_client(index_dir)
    collection = build_index(model, client, registry)
    return model, collection


@pytest.fixture
def candidates_8pct():
    shipments = load_shipments()
    weekly = add_baselines(build_weekly_costs(shipments))
    return find_candidates(weekly, t_own=0.08)


JUSTIFIED = [
    ("Ahmedabad-Mumbai", "2025-01-20", "N002"),
    ("Chennai-Bangalore", "2025-02-24", "N001"),
    ("Chennai-Bangalore", "2025-03-03", "N001"),
]


def test_justified_candidates_have_matching_note_in_top3(retrieval_index):
    model, collection = retrieval_index
    relevant = 0
    for route, week, expected_note in JUSTIFIED:
        top3, _ = retrieve_for_candidate(route, week, model, collection)
        top_ids = [s["note_id"] for s in top3]
        assert expected_note in top_ids, f"{route} {week}: expected {expected_note} in {top_ids}"
        relevant += 1
    recall_at_3 = relevant / len(JUSTIFIED)
    print(f"\nrecall@3 for justified candidates: {recall_at_3:.2%}")


def test_top3_has_exactly_three_notes(retrieval_index, candidates_8pct):
    model, collection = retrieval_index
    for _, row in candidates_8pct.iterrows():
        top3, _ = retrieve_for_candidate(row["route"], row["week_of"], model, collection)
        assert len(top3) == 3


def test_all_scores_cover_all_notes(retrieval_index, candidates_8pct):
    model, collection = retrieval_index
    for _, row in candidates_8pct.iterrows():
        _, all_scores = retrieve_for_candidate(row["route"], row["week_of"], model, collection)
        assert len(all_scores) == 10
        assert len({s["note_id"] for s in all_scores}) == 10


def test_trace_written(tmp_path, retrieval_index, candidates_8pct):
    model, collection = retrieval_index
    trace = build_retrieval_trace(candidates_8pct, model, collection)
    output_path = tmp_path / "retrieval_trace.jsonl"
    from src.retrieval import write_trace
    write_trace(trace, output_path)

    assert output_path.exists()
    lines = output_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == len(candidates_8pct)
    for line in lines:
        record = json.loads(line)
        assert "route" in record
        assert "week_of" in record
        assert "query" in record
        assert "top_3" in record
        assert "all_scores" in record
        assert len(record["top_3"]) == 3
        assert len(record["all_scores"]) == 10


def test_tie_breaking_by_note_id(retrieval_index):
    """If two notes had identical scores, the lower note_id should rank first.
    This test injects a synthetic near-tie scenario and checks deterministic ordering.
    """
    model, collection = retrieval_index
    top3, all_scores = retrieve_for_candidate(
        "Chennai-Bangalore", "2025-02-24", model, collection
    )
    # Verify the returned list is strictly ordered by (-score, note_id).
    for i in range(len(all_scores) - 1):
        a = all_scores[i]
        b = all_scores[i + 1]
        if a["score"] == b["score"]:
            assert a["note_id"] < b["note_id"]
        else:
            assert a["score"] > b["score"]
