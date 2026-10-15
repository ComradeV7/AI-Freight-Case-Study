"""Compare two flagged_routes CSVs.

Reports whether the non-reason columns are identical, and lists rows where the
reason column differs.  Used by run_3x.sh to show that deterministic runs are
identical except for LLM wording when temperature is raised.
"""

import sys
from pathlib import Path

import pandas as pd

NON_REASON_COLS = [
    "route",
    "week_of",
    "cost_per_tonne_km",
    "vs_own_history",
    "vs_similar_routes",
    "flagged",
    "matched_note_id",
]


def compare(path_a: Path, path_b: Path) -> dict:
    a = pd.read_csv(path_a, dtype=str)
    b = pd.read_csv(path_b, dtype=str)

    # Align by row order; the pipeline sorts by week_of then route deterministically.
    non_reason_equal = a[NON_REASON_COLS].equals(b[NON_REASON_COLS])

    reason_diffs = []
    if "reason" in a.columns and "reason" in b.columns:
        for idx, (ra, rb) in enumerate(zip(a["reason"], b["reason"])):
            if str(ra) != str(rb):
                reason_diffs.append(
                    {
                        "row": idx,
                        "route": a.loc[idx, "route"],
                        "week_of": a.loc[idx, "week_of"],
                        "reason_a": str(ra),
                        "reason_b": str(rb),
                    }
                )

    return {
        "non_reason_columns_identical": bool(non_reason_equal),
        "rows_compared": len(a),
        "reason_differences": reason_diffs,
    }


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python scripts/compare_non_reason.py <a.csv> <b.csv>")
        sys.exit(1)

    result = compare(Path(sys.argv[1]), Path(sys.argv[2]))

    print("Non-reason columns identical:", result["non_reason_columns_identical"])
    print("Rows compared:", result["rows_compared"])
    print("Reason differences:", len(result["reason_differences"]))
    for diff in result["reason_differences"]:
        print(f"\nRow {diff['row']} | {diff['route']} {diff['week_of']}")
        print(f"  A: {diff['reason_a']}")
        print(f"  B: {diff['reason_b']}")


if __name__ == "__main__":
    main()
