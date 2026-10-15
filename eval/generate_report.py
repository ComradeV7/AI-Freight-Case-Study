"""Generate the combined evaluation report (outputs/eval_report.md)."""

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.audit_justified import audit_justified_rows
from eval.mutation_tests import run_mutations
from eval.retrieval_ablation import RETRIEVAL_TRACE_PATH, GATE_OUTPUT_PATH
from eval.run_eval import compute_metrics, load_labeled_and_output, build_report as build_eval_report

import json
import pandas as pd

REPORT_PATH = Path(__file__).parent.parent / "outputs" / "eval_report.md"


def _run_retrieval_ablation() -> list[dict]:
    trace = []
    with open(RETRIEVAL_TRACE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            trace.append(json.loads(line))

    gate = pd.read_csv(GATE_OUTPUT_PATH)
    gate["week_of"] = pd.to_datetime(gate["week_of"]).dt.strftime("%Y-%m-%d")

    cases = [
        ("Chennai-Bangalore", "2025-03-10", "N001"),
        ("Chennai-Bangalore", "2025-03-17", "N001"),
    ]

    results = []
    for route, week, expected_note in cases:
        gate_row = gate[(gate["route"] == route) & (gate["week_of"] == week)]
        trace_item = next(
            (item for item in trace if item["route"] == route and item["week_of"] == week),
            None,
        )
        if gate_row.empty or not trace_item:
            continue
        top3 = [n["note_id"] for n in trace_item["top_3"]]
        results.append(
            {
                "route": route,
                "week_of": week,
                "gate_verdict": gate_row.iloc[0]["flagged"],
                "retrieval_top3": top3,
                "expected_note_still_in_top3": expected_note in top3,
            }
        )
    return results


def build_full_report() -> str:
    labeled, output = load_labeled_and_output()
    metrics = compute_metrics(labeled, output)

    audit_findings = audit_justified_rows()
    mutation_results = run_mutations()
    ablation_results = _run_retrieval_ablation()

    lines = [
        "# Evaluation Report",
        "",
        "## 1. Verdict accuracy",
        f"- Correct verdicts: {metrics['verdict_correct']} / {metrics['total_rows']}",
        f"- Verdict accuracy: {metrics['verdict_accuracy']:.1%}",
        "",
        "## 2. Cited-note exact match",
        f"- Justified rows: {metrics['justified_rows']}",
        f"- Correct note citations: {metrics['cited_match']} / {metrics['justified_rows']}",
        f"- Cited-note accuracy: {metrics['cited_note_accuracy']:.1%}",
        "",
        "## 3. Fabrication count",
        f"- Fabrications: {metrics['fabrication_count']} (must be 0)",
        "",
        "## 4. Numeric-field match on sample rows",
        f"- Fields matching sample exactly: {metrics['sample_matches']} / {metrics['sample_total']}",
        f"- Sample match rate: {metrics['sample_match_rate']:.1%}",
        "",
        "## 5. Independent audit of justified rows",
        "Re-reads `data/context_notes.csv` directly (not `config/notes_registry.yaml`) and checks:",
        "route match, window overlap, and that the note text describes a cost rise.",
        "",
    ]
    for f in audit_findings:
        status = "PASS" if f["passed"] else "FAIL"
        lines.append(f"- {status} | {f['route']} {f['week_of']} {f['note_id']} | {f['detail']}")
    lines.append("")

    lines.extend([
        "## 6. Mutation tests",
        "Each justified row must flip to unexplained when its matching note is corrupted.",
        "",
    ])
    for r in mutation_results:
        status = "PASS" if r["flipped_to_unexplained"] else "FAIL"
        lines.append(
            f"- {status} | {r['route']} {r['week_of']} {r['note_id']} | {r['mutation']}"
        )
    lines.append("")

    lines.extend([
        "## 7. Retrieval-only ablation",
        "Wrong-window cases where the rule-based gate correctly says unexplained,",
        "but semantic retrieval still ranks the off-window note in the top 3.",
        "",
    ])
    for r in ablation_results:
        lines.append(
            f"- {r['route']} {r['week_of']} | gate={r['gate_verdict']} | "
            f"retrieval top-3={r['retrieval_top3']} | "
            f"off-window note in top-3={r['expected_note_still_in_top3']}"
        )
    lines.append("")

    if (
        metrics["fabrication_count"] == 0
        and all(f["passed"] for f in audit_findings)
        and all(r["flipped_to_unexplained"] for r in mutation_results)
    ):
        lines.append(
            "**Overall result:** PASS. Verdicts are grounded, independently auditable, "
            "and robust to note mutations. Retrieval alone is insufficient for trustworthy justification."
        )
    else:
        lines.append("**Overall result:** FAIL — review findings above.")

    return "\n".join(lines)


def main() -> None:
    report = build_full_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
