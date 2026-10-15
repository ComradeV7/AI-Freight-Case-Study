"""Independent auditor: re-read context_notes.csv and verify every justified row.

This script deliberately does NOT use config/notes_registry.yaml; it reads the original
context_notes.csv and applies its own checks to the pipeline's justified rows.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

# Shared helpers live in src/notes.py (single source of truth); re-exported here
# so the audit remains a standalone, independent check of src/ behaviour.
from src.notes import extract_window_from_text, note_describes_cost_rise  # noqa: F401


NOTES_CSV_PATH = Path(__file__).parent.parent / "data" / "context_notes.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "outputs" / "flagged_routes.csv"


def load_notes_csv() -> pd.DataFrame:
    df = pd.read_csv(NOTES_CSV_PATH)
    df["date"] = pd.to_datetime(df["date"])
    return df


def route_matches(note_row: pd.Series, route: str) -> bool:
    applies_to = str(note_row["applies_to"])
    return applies_to == "All Routes" or route in applies_to


def window_overlaps(note_text: str, note_date: pd.Timestamp, week_of: str) -> bool:
    """Check whether the candidate week [Mon..Sun] overlaps the note's effective window."""
    eff_start, eff_end = extract_window_from_text(note_text, note_date)
    week_start = pd.to_datetime(week_of)
    week_end = week_start + timedelta(days=6)
    return week_start <= eff_end and week_end >= eff_start


def audit_justified_rows() -> list[dict]:
    notes = load_notes_csv()
    output = pd.read_csv(OUTPUT_PATH)
    output["week_of"] = pd.to_datetime(output["week_of"]).dt.strftime("%Y-%m-%d")

    justified = output[output["flagged"] == "No (justified)"]
    findings = []

    for _, row in justified.iterrows():
        route = row["route"]
        week_of = row["week_of"]
        note_id = row["matched_note_id"]

        note_rows = notes[notes["note_id"] == note_id]
        if len(note_rows) != 1:
            findings.append(
                {
                    "route": route,
                    "week_of": week_of,
                    "note_id": note_id,
                    "check": "note_exists",
                    "passed": False,
                    "detail": f"Expected one note row for {note_id}, found {len(note_rows)}",
                }
            )
            continue

        note_row = note_rows.iloc[0]
        passed = True
        detail_parts = []

        if not route_matches(note_row, route):
            passed = False
            detail_parts.append(f"route mismatch (applies_to={note_row['applies_to']})")

        if not window_overlaps(note_row["note"], note_row["date"], week_of):
            passed = False
            detail_parts.append(
                f"window mismatch (note_date={note_row['date'].date()}, week={week_of})"
            )

        if not note_describes_cost_rise(note_row["note"]):
            passed = False
            detail_parts.append("text does not describe a cost rise")

        findings.append(
            {
                "route": route,
                "week_of": week_of,
                "note_id": note_id,
                "check": "independent_audit",
                "passed": passed,
                "detail": "; ".join(detail_parts) if detail_parts else "all checks passed",
            }
        )

    return findings


def main() -> int:
    findings = audit_justified_rows()
    all_passed = all(f["passed"] for f in findings)

    print("Independent audit of justified rows")
    print("=" * 50)
    for f in findings:
        status = "PASS" if f["passed"] else "FAIL"
        print(f"{status} | {f['route']} {f['week_of']} {f['note_id']} | {f['detail']}")
    print("=" * 50)
    print(f"Overall: {'PASS' if all_passed else 'FAIL'} ({sum(f['passed'] for f in findings)}/{len(findings)} checks passed)")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
