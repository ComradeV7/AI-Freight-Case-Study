"""Mutation tests: verify that justified rows flip to unexplained when notes are corrupted."""

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gate import evaluate_candidate
from src.load import load_shipments
from src.notes import load_notes_registry
from src.output import FLAGGED_PATH as OUTPUT_PATH
from src.weekly import build_weekly_costs
from src.baselines import add_baselines
from src.flagging import find_candidates, load_params


def _shift_date(date_str: str, weeks: int) -> str:
    d = pd.to_datetime(date_str) + timedelta(weeks=weeks)
    return d.strftime("%Y-%m-%d")


def run_mutations() -> list[dict]:
    output = pd.read_csv(OUTPUT_PATH)
    output["week_of"] = pd.to_datetime(output["week_of"]).dt.strftime("%Y-%m-%d")
    justified = output[output["flagged"] == "No (justified)"]
    registry = load_notes_registry()

    results = []
    for _, row in justified.iterrows():
        route = row["route"]
        week_of = row["week_of"]
        note_id = row["matched_note_id"]
        note = registry[note_id]

        mutations = [
            ("date_shifted_3_weeks", {
                **note,
                "effective_from": _shift_date(note["effective_from"], 3),
                "effective_to": _shift_date(note["effective_to"], 3),
            }),
            ("route_swapped", {
                **note,
                "scope": ["Wrong-Route"],
            }),
            ("text_no_effect", {
                **note,
                "polarity": "no_effect",
                "source_text": "Scheduled maintenance work was completed; costs were not significantly affected.",
            }),
        ]

        for mutation_name, mutated_note in mutations:
            mutated_registry = {note_id: mutated_note}
            matched, _ = evaluate_candidate(route, week_of, mutated_registry)
            flipped = matched is None
            results.append(
                {
                    "route": route,
                    "week_of": week_of,
                    "note_id": note_id,
                    "mutation": mutation_name,
                    "flipped_to_unexplained": flipped,
                }
            )
            status = "PASS" if flipped else "FAIL"
            print(f"{status} | {route} {week_of} {note_id} | {mutation_name}")

    return results


def main() -> int:
    print("Mutation tests: justified rows must flip to unexplained under note corruption")
    print("=" * 70)
    results = run_mutations()
    all_flipped = all(r["flipped_to_unexplained"] for r in results)
    print("=" * 70)
    print(f"Overall: {'PASS' if all_flipped else 'FAIL'} ({sum(r['flipped_to_unexplained'] for r in results)}/{len(results)} mutations flipped)")
    return 0 if all_flipped else 1


if __name__ == "__main__":
    sys.exit(main())
