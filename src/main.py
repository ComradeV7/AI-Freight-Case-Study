"""Full pipeline entry point.

Loads shipments, computes weekly cost-per-tonne-km, baselines, flags rising
routes, retrieves supporting notes, applies the rule gate, generates
explanations, and writes the final deliverables.

Offline by default: explanations resolve cache -> template and never touch
the network unless --live is passed.

Portable by default: every input/output path and the flagging threshold is
configurable via CLI, so the pipeline runs unchanged on unseen CSV files.
"""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.explain import explain_candidates
from src.output import (
    build_all_weeks_grid,
    format_flagged_output,
    write_all_weeks_grid,
    write_flagged_routes,
)


DEFAULT_SHIPMENTS = "data/shipment_records.csv"
DEFAULT_NOTES = "data/context_notes.csv"
DEFAULT_OUTPUT = "outputs/flagged_routes.csv"


def main(
    *,
    live: bool = False,
    no_cache: bool = False,
    temperature=None,
    shipments_path: str | Path | None = None,
    notes_path: str | Path | None = None,
    output_path: str | Path | None = None,
    threshold: float | None = None,
) -> dict:
    """Run the pipeline and return the paths that were written.

    no_cache=True ignores the shared cache: reads miss it entirely and any
    live responses are written to a separate cache directory, so the shared
    cache and canonical outputs stay untouched.
    """
    from src.baselines import add_baselines
    from src.flagging import find_candidates, load_params
    from src.gate import gate_candidates, write_gate_audit
    from src.load import load_shipments
    from src.notes import build_registry
    from src.retrieval import build_index, build_retrieval_trace, get_client, get_model
    from src.weekly import build_weekly_costs

    if shipments_path is None:
        shipments_path = DEFAULT_SHIPMENTS
    if notes_path is None:
        notes_path = DEFAULT_NOTES
    if output_path is None:
        output_path = "outputs_nocache/flagged_routes.csv" if no_cache else DEFAULT_OUTPUT
    flagged_path = Path(output_path)
    out_dir = flagged_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    params = load_params()
    t_own = threshold if threshold is not None else params["flagging"]["t_own"]

    print("Loading shipments...")
    shipments = load_shipments(shipments_path)

    print("Building weekly costs and baselines...")
    weekly = add_baselines(build_weekly_costs(shipments))

    print("Finding flag candidates...")
    candidates = find_candidates(weekly, t_own=t_own)
    print(f"  {len(candidates)} candidates")

    # Notes registry: curated YAML for known notes, derived on the fly for
    # unseen/modified notes so a grader's CSVs never crash the gate.
    registry = build_registry(notes_path)

    print("Applying rule gate...")
    gated = gate_candidates(candidates, registry)
    write_gate_audit(gated, path=out_dir / "gate_audit.json")

    print("Building retrieval trace...")
    model = get_model()
    client = get_client()
    collection = build_index(model, client, registry)
    trace = build_retrieval_trace(candidates, model, collection)

    trace_path = out_dir / "retrieval_trace.jsonl"
    with open(trace_path, "w", encoding="utf-8") as f:
        for record in trace:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print("Generating explanations...")
    explained = explain_candidates(
        gated,
        retrieval_trace=trace,
        live=live,
        no_cache_dir=no_cache,
        temperature=temperature,
    )

    print("Writing outputs...")
    flagged_output = format_flagged_output(explained)
    write_flagged_routes(flagged_output, path=flagged_path)

    grid = build_all_weeks_grid(weekly)
    grid_path = out_dir / "all_weeks_grid.csv"
    write_all_weeks_grid(grid, path=grid_path)

    mode = "live" if live else "offline"
    print(f"Wrote {len(flagged_output)} flagged rows ({mode}) to {flagged_path}")
    print(f"Wrote {len(grid)} route-week rows to {grid_path}")

    return {"flagged": flagged_path, "grid": grid_path, "trace": trace_path}


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="FreightTiger anomaly pipeline")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow live LLM API calls (cache is still checked first).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the shared cache and write to a separate output directory.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Override the configured temperature (for the reproducibility test).",
    )
    parser.add_argument(
        "--shipments",
        default=DEFAULT_SHIPMENTS,
        help="Shipment records CSV (default: data/shipment_records.csv).",
    )
    parser.add_argument(
        "--notes",
        default=DEFAULT_NOTES,
        help="Context notes CSV (default: data/context_notes.csv).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Flagged routes output CSV (default: outputs/flagged_routes.csv).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Own-history flagging threshold (default: from config/params.yaml).",
    )
    return parser.parse_args(argv)


def cli() -> None:
    args = _parse_args()
    main(
        live=args.live,
        no_cache=args.no_cache,
        temperature=args.temperature,
        shipments_path=args.shipments,
        notes_path=args.notes,
        output_path=args.output,
        threshold=args.threshold,
    )


if __name__ == "__main__":
    cli()
