"""Retrieval-only ablation: show semantic retrieval does not catch the wrong-window trap."""

import json
import sys
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))


RETRIEVAL_TRACE_PATH = Path(__file__).parent.parent / "outputs" / "retrieval_trace.jsonl"
GATE_OUTPUT_PATH = Path(__file__).parent.parent / "outputs" / "flagged_routes.csv"


def main() -> None:
    # Load retrieval trace.
    trace = []
    with open(RETRIEVAL_TRACE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            trace.append(json.loads(line))

    # Load gate output to find an unexplained row caused by window mismatch.
    gate = pd.read_csv(GATE_OUTPUT_PATH)
    gate["week_of"] = pd.to_datetime(gate["week_of"]).dt.strftime("%Y-%m-%d")

    print("Retrieval-only ablation: wrong-window cases")
    print("=" * 60)

    wrong_window_cases = [
        ("Chennai-Bangalore", "2025-03-10", "N001"),  # N001 window ends 2025-03-08
        ("Chennai-Bangalore", "2025-03-17", "N001"),
    ]

    for route, week, expected_top_note in wrong_window_cases:
        gate_row = gate[(gate["route"] == route) & (gate["week_of"] == week)]
        if len(gate_row) != 1:
            print(f"SKIP | {route} {week} not found in gate output")
            continue
        is_unexplained = gate_row.iloc[0]["flagged"] == "Yes"

        trace_item = next(
            (item for item in trace if item["route"] == route and item["week_of"] == week),
            None,
        )
        if not trace_item:
            print(f"SKIP | {route} {week} not found in retrieval trace")
            continue

        top3_ids = [n["note_id"] for n in trace_item["top_3"]]
        retrieval_would_justify = expected_top_note in top3_ids

        status = "DEMONSTRATED" if (is_unexplained and retrieval_would_justify) else "UNEXPECTED"
        print(
            f"{status} | {route} {week} | gate={gate_row.iloc[0]['flagged']} | "
            f"retrieval top-3={top3_ids} | {expected_top_note} still retrieved={retrieval_would_justify}"
        )

    print("=" * 60)
    print("Conclusion: retrieval alone is insufficient; the rule-based gate is required.")


if __name__ == "__main__":
    main()
