"""Gate / justification layer: decide whether a flagged candidate is justified by a note."""

import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.baselines import add_baselines
from src.flagging import find_candidates, load_params
from src.load import load_shipments
from src.notes import build_registry, load_notes_registry
from src.weekly import build_weekly_costs


GATE_AUDIT_PATH = Path(__file__).parent.parent / "outputs" / "gate_audit.json"


def _parse_date(value: pd.Timestamp | str) -> pd.Timestamp:
    if isinstance(value, pd.Timestamp):
        return value.normalize()
    return pd.to_datetime(value).normalize()


def _week_range(week_of: pd.Timestamp | str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = _parse_date(week_of)
    end = start + timedelta(days=6)
    return start, end


def _scope_passes(route: str, scope) -> bool:
    return scope == "ALL" or (isinstance(scope, list) and route in scope)


def _window_passes(
    week_of: pd.Timestamp | str,
    effective_from: str,
    effective_to: str,
) -> bool:
    week_start, week_end = _week_range(week_of)
    eff_from = _parse_date(effective_from)
    eff_to = _parse_date(effective_to)
    return week_start <= eff_to and week_end >= eff_from


def _polarity_passes(polarity: str) -> bool:
    return polarity == "causes_rise"


def evaluate_candidate(
    route: str,
    week_of: pd.Timestamp | str,
    registry: dict,
) -> tuple[str | None, list[dict]]:
    """Evaluate every note against a candidate. Returns the matched note_id (or None) and the full trace."""
    trace = []
    matches = []

    for note_id, entry in registry.items():
        scope_ok = _scope_passes(route, entry["scope"])
        window_ok = _window_passes(week_of, entry["effective_from"], entry["effective_to"])
        polarity_ok = _polarity_passes(entry["polarity"])
        is_match = scope_ok and window_ok and polarity_ok

        trace.append(
            {
                "note_id": note_id,
                "scope": {"expected": entry["scope"], "passed": bool(scope_ok)},
                "window": {
                    "effective_from": entry["effective_from"],
                    "effective_to": entry["effective_to"],
                    "passed": bool(window_ok),
                },
                "polarity": {"expected": entry["polarity"], "passed": bool(polarity_ok)},
                "match": bool(is_match),
            }
        )

        if is_match:
            matches.append((note_id, entry))

    if not matches:
        return None, trace

    # Tie-breaker: route-specific before ALL, then earliest effective_from, then lowest note_id.
    def sort_key(item):
        note_id, entry = item
        is_all = 1 if entry["scope"] == "ALL" else 0
        eff_from = _parse_date(entry["effective_from"])
        return (is_all, eff_from, note_id)

    matches.sort(key=sort_key)
    return matches[0][0], trace


def _build_reason(
    matched_note_id: str | None,
    registry: dict,
    route: str,
    week_of: pd.Timestamp | str,
) -> str:
    if matched_note_id is None:
        return (
            "No matching note found for this route or date range. "
            "Cost rise looks unexplained and worth a human review."
        )

    note = registry[matched_note_id]
    return (
        f"Matches note {matched_note_id} dated {note['effective_from']}: "
        f"{note['source_text']}"
    )


def gate_candidates(
    candidates: pd.DataFrame,
    registry: dict | None = None,
    notes_path: Path | str | None = None,
) -> pd.DataFrame:
    """Apply the note-matching gate to every candidate and produce the final verdict columns.

    With no explicit ``registry``, the registry is built from the notes CSV:
    curated YAML entries for known notes, derived entries for unseen/modified
    notes (see ``src.notes.build_registry``).
    """
    if registry is None:
        registry = build_registry(notes_path)

    rows = []
    for _, row in candidates.iterrows():
        route = row["route"]
        week_of = row["week_of"]
        matched_note_id, trace = evaluate_candidate(route, week_of, registry)

        flagged = "No (justified)" if matched_note_id else "Yes"
        note = registry.get(matched_note_id) if matched_note_id else None
        rows.append(
            {
                "route": route,
                "week_of": week_of,
                "cost_per_tonne_km": row["cost_per_tonne_km"],
                "vs_own_history": row["pct_vs_history"],
                "vs_similar_routes": row["pct_vs_peers"],
                "flagged": flagged,
                "matched_note_id": matched_note_id or "",
                "matched_note_date": note["effective_from"] if note else "",
                "matched_note_text": note["source_text"] if note else "",
                "matched_note_window": f"{note['effective_from']}..{note['effective_to']}" if note else "",
                "reason": _build_reason(matched_note_id, registry, route, week_of),
                "trace": trace,
            }
        )

    return pd.DataFrame(rows)


def _clean_for_json(value):
    if isinstance(value, float):
        if pd.isna(value):
            return None
        return value
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def write_gate_audit(result: pd.DataFrame, path: Path | str | None = None) -> None:
    """Persist the full per-candidate, per-note rule trace to JSON."""
    if path is None:
        path = GATE_AUDIT_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    records = result.to_dict("records")
    cleaned = []
    for rec in records:
        cleaned_rec = {k: _clean_for_json(v) for k, v in rec.items()}
        cleaned.append(cleaned_rec)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)


def main() -> None:
    params = load_params()
    t_own = params["flagging"]["t_own"]

    shipments = load_shipments()
    weekly = add_baselines(build_weekly_costs(shipments))
    candidates = find_candidates(weekly, t_own=t_own)

    result = gate_candidates(candidates)
    write_gate_audit(result)
    print(f"Wrote gate audit for {len(result)} candidates to {GATE_AUDIT_PATH}")


if __name__ == "__main__":
    main()
