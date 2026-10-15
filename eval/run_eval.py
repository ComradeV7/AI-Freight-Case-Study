"""Evaluation harness: compare pipeline output against manual labels."""

import sys
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))


LABELED_PATH = Path(__file__).parent.parent / "eval" / "labeled.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "outputs" / "flagged_routes.csv"
REPORT_PATH = Path(__file__).parent.parent / "outputs" / "eval_report.md"

SAMPLE_CHECK = {
    ("Delhi-Jaipur", "2024-11-11"): {
        "cost_per_tonne_km": "4.17",
        "vs_own_history": "+35.5% vs this route's past average",
        "vs_similar_routes": "+21.0% vs similar-length routes this week",
    },
    ("Ahmedabad-Mumbai", "2025-01-20"): {
        "cost_per_tonne_km": "3.29",
        "vs_own_history": "+29.5% vs this route's past average",
        "vs_similar_routes": "+22.5% vs similar-length routes this week",
    },
    ("Mumbai-Pune", "2025-09-15"): {
        "cost_per_tonne_km": "3.98",
        "vs_own_history": "+9.2% vs this route's past average",
        "vs_similar_routes": "+23.6% vs similar-length routes this week",
    },
}


def load_labeled_and_output() -> tuple[pd.DataFrame, pd.DataFrame]:
    labeled = pd.read_csv(LABELED_PATH)
    output = pd.read_csv(OUTPUT_PATH)
    output["week_of"] = pd.to_datetime(output["week_of"]).dt.strftime("%Y-%m-%d")
    return labeled, output


def compute_metrics(labeled: pd.DataFrame, output: pd.DataFrame) -> dict:
    merged = labeled.merge(output, on=["route", "week_of"], suffixes=("_expected", "_actual"))
    if len(merged) != len(labeled):
        raise ValueError("Not all labeled rows found in pipeline output")

    # Verdict accuracy.
    verdict_correct = (merged["expected_flag"] == merged["flagged"]).sum()
    total = len(merged)
    verdict_accuracy = verdict_correct / total if total else 0.0

    # Cited-note exact match (only for justified rows).
    justified_mask = merged["expected_flag"] == "No (justified)"
    justified = merged[justified_mask]
    cited_match = (
        justified["expected_note_id"].astype(str) == justified["matched_note_id"].astype(str)
    ).sum()
    cited_note_accuracy = cited_match / len(justified) if len(justified) else 1.0

    # Fabrication count: model says justified but label says unexplained,
    # or model cites a different note than expected.
    false_justifications = ((merged["flagged"] == "No (justified)") & (merged["expected_flag"] == "Yes")).sum()
    wrong_note = (
        justified_mask
        & (merged["flagged"] == "No (justified)")
        & (merged["expected_note_id"].astype(str) != merged["matched_note_id"].astype(str))
    ).sum()
    fabrication_count = int(false_justifications + wrong_note)

    # Numeric-field match on three sample rows.
    sample_matches = 0
    sample_total = 0
    for (route, week), expected in SAMPLE_CHECK.items():
        row = output[(output["route"] == route) & (output["week_of"] == week)]
        if len(row) != 1:
            continue
        row = row.iloc[0]
        for field, expected_value in expected.items():
            sample_total += 1
            if str(row[field]) == expected_value:
                sample_matches += 1

    return {
        "total_rows": total,
        "verdict_correct": int(verdict_correct),
        "verdict_accuracy": verdict_accuracy,
        "justified_rows": int(justified_mask.sum()),
        "cited_match": int(cited_match),
        "cited_note_accuracy": cited_note_accuracy,
        "fabrication_count": fabrication_count,
        "sample_matches": sample_matches,
        "sample_total": sample_total,
        "sample_match_rate": sample_matches / sample_total if sample_total else 0.0,
    }


def build_report(metrics: dict) -> str:
    lines = [
        "# Evaluation Report",
        "",
        "## Verdict accuracy",
        f"- Correct verdicts: {metrics['verdict_correct']} / {metrics['total_rows']}",
        f"- Verdict accuracy: {metrics['verdict_accuracy']:.1%}",
        "",
        "## Cited-note exact match",
        f"- Justified rows: {metrics['justified_rows']}",
        f"- Correct note citations: {metrics['cited_match']} / {metrics['justified_rows']}",
        f"- Cited-note accuracy: {metrics['cited_note_accuracy']:.1%}",
        "",
        "## Fabrication count",
        f"- Fabrications: {metrics['fabrication_count']} (must be 0)",
        "",
        "## Numeric-field match on sample rows",
        f"- Fields matching sample exactly: {metrics['sample_matches']} / {metrics['sample_total']}",
        f"- Sample match rate: {metrics['sample_match_rate']:.1%}",
        "",
    ]
    if metrics["fabrication_count"] == 0:
        lines.append("**Result:** No fabrications detected. Verdicts and citations are grounded.")
    else:
        lines.append("**Result:** Fabrications detected — review justified rows.")
    return "\n".join(lines)


def main() -> dict:
    labeled, output = load_labeled_and_output()
    metrics = compute_metrics(labeled, output)
    report = build_report(metrics)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport written to {REPORT_PATH}")
    return metrics


if __name__ == "__main__":
    main()
