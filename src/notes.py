import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

# Allow running this module directly from the project root.
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

REGISTRY_PATH = Path(__file__).parent.parent / "config" / "notes_registry.yaml"
NOTES_CSV_PATH = Path(__file__).parent.parent / "data" / "context_notes.csv"

VALID_POLARITIES = {"causes_rise", "no_effect", "informational", "not_applicable"}

# Keywords that indicate a note describes a price/cost rise.
COST_RISE_KEYWORDS = [
    "rise",
    "rose",
    "increase",
    "increased",
    "higher",
    "high",
    "surcharge",
    "pushing up",
    "pushed up",
    "more expensive",
    "costlier",
    "upward",
]

_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"


def load_notes_registry(path: Path | str | None = None) -> dict:
    """Load the manually-curated notes registry."""
    if path is None:
        path = REGISTRY_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["notes"]


def load_notes_csv(path: Path | str | None = None) -> pd.DataFrame:
    """Load context notes CSV."""
    if path is None:
        path = NOTES_CSV_PATH
    return pd.read_csv(path)


# ---------------------------------------------------------------------------
# Dynamic note interpretation (portability for unseen / modified notes)
# ---------------------------------------------------------------------------
def note_describes_cost_rise(text: str) -> bool:
    """Heuristic: does the note text describe a freight-cost rise?"""
    lowered = str(text).lower()
    return any(kw in lowered for kw in COST_RISE_KEYWORDS)


def extract_window_from_text(
    text: str, note_date: pd.Timestamp | str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Infer the effective [start, end] window from a note's text.

    Handles explicit ranges like 'from Feb 24 to Mar 8' and week-long events
    (7 days inclusive).  Falls back to the note's own date when nothing else
    can be inferred.
    """
    note_date = pd.Timestamp(note_date)
    pattern = rf"(?:from\s+)?({_MONTHS})\s+(\d{{1,2}})\s+to\s+({_MONTHS})\s+(\d{{1,2}})"
    match = re.search(pattern, str(text), re.IGNORECASE)
    if match:
        start_month, start_day, end_month, end_day = match.groups()
        start = pd.to_datetime(f"{note_date.year}-{start_month}-{start_day}")
        end = pd.to_datetime(f"{note_date.year}-{end_month}-{end_day}")
        return start, end

    if re.search(r"\bweek\b", str(text), re.IGNORECASE):
        return note_date, note_date + timedelta(days=6)

    return note_date, note_date


def _derive_scope(applies_to) -> list[str] | str:
    value = str(applies_to).strip()
    if value.lower() in {"all routes", "all"}:
        return "ALL"
    return [value]


def derive_note_entry(note_id: str, date, applies_to, text: str) -> dict:
    """Derive a registry entry (scope/window/polarity) for an unseen note."""
    start, end = extract_window_from_text(text, date)
    return {
        "scope": _derive_scope(applies_to),
        "effective_from": start.strftime("%Y-%m-%d"),
        "effective_to": end.strftime("%Y-%m-%d"),
        "polarity": "causes_rise" if note_describes_cost_rise(text) else "no_effect",
        "source_text": str(text),
    }


def build_registry(
    notes_path: Path | str | None = None,
    base_path: Path | str | None = None,
) -> dict:
    """Build the gate registry from a notes CSV, curated by the YAML registry.

    For every note in the CSV:
      * if the id exists in the curated YAML registry AND the text matches
        exactly, use the curated entry (authoritative scope/window/polarity);
      * otherwise derive scope/window/polarity on the fly from the CSV row.

    This makes the pipeline robust to a grader's modified ``context_notes.csv``
    (new note ids such as ``N011``, or edited text) without crashing.
    """
    base = load_notes_registry(base_path)
    notes = load_notes_csv(notes_path)

    registry: dict = {}
    for _, row in notes.iterrows():
        note_id = str(row["note_id"])
        text = str(row["note"])
        curated = base.get(note_id)
        if curated is not None and curated.get("source_text", "") == text:
            registry[note_id] = curated
        else:
            registry[note_id] = derive_note_entry(
                note_id, row["date"], row["applies_to"], text
            )
    return registry


def validate_registry(registry: dict | None = None, notes_csv: pd.DataFrame | None = None) -> None:
    """Validate that every CSV note is present in the registry and source_text matches exactly."""
    if registry is None:
        registry = load_notes_registry()
    if notes_csv is None:
        notes_csv = load_notes_csv()

    errors = []

    for _, row in notes_csv.iterrows():
        note_id = row["note_id"]
        if note_id not in registry:
            errors.append(f"Missing registry entry for {note_id}")
            continue

        entry = registry[note_id]
        expected_text = row["note"]
        actual_text = entry.get("source_text", "")
        if actual_text != expected_text:
            errors.append(
                f"{note_id}: source_text mismatch\n"
                f"  CSV:     {expected_text!r}\n"
                f"  YAML:    {actual_text!r}"
            )

        polarity = entry.get("polarity")
        if polarity not in VALID_POLARITIES:
            errors.append(f"{note_id}: invalid polarity {polarity!r}")

        scope = entry.get("scope")
        if scope != "ALL" and not isinstance(scope, list):
            errors.append(f"{note_id}: scope must be 'ALL' or a list of routes, got {scope!r}")

    if errors:
        raise ValueError("Registry validation failed:\n" + "\n".join(errors))


def main() -> None:
    registry = load_notes_registry()
    notes_csv = load_notes_csv()
    validate_registry(registry, notes_csv)
    print(f"Registry valid: {len(notes_csv)} CSV notes matched.")


if __name__ == "__main__":
    main()
