"""Cross-check the curated notes registry against a local LLM.

Runs each context note past a local model at temperature 0 and compares the model's
JSON response with the values in config/notes_registry.yaml. The YAML is the source of
truth; any disagreements are printed and should be recorded in README.md.

Requires a local OpenAI-compatible endpoint. Defaults to Ollama on localhost:11434.
Set OLLAMA_MODEL and OLLAMA_URL env vars to override.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.notes import load_notes_csv, load_notes_registry, validate_registry

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

PROMPT_TEMPLATE = '''You are a strict assistant extracting structured fields from a freight-cost context note.

Given the note below, return a single JSON object with these exact keys:
- "scope": either the string "ALL" or a list of route strings like ["Chennai-Bangalore"]
- "effective_from": ISO date string YYYY-MM-DD
- "effective_to": inclusive ISO date string YYYY-MM-DD
- "polarity": one of "causes_rise", "no_effect", "informational", "not_applicable"

Rules:
- "causes_rise" only if the note describes a reason costs actually increased.
- "no_effect" if the note explicitly says costs were not significantly affected or no disruptions.
- "informational" if it describes improved/normal conditions without a cost increase.
- "not_applicable" if the affected routes are not in the dataset.
- If scope is ALL, use "ALL".
- effective_to is inclusive.

Return only the JSON object, no markdown, no explanation.

Note:
"{note_text}"'''


def _call_llm(prompt: str) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
        "format": "json",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return json.loads(body["response"])


def _normalise_scope(value):
    if value == "ALL":
        return "ALL"
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return sorted(value)
    raise ValueError(f"Unexpected scope type: {value!r}")


def cross_check() -> list[dict]:
    registry = load_notes_registry()
    notes_csv = load_notes_csv()
    validate_registry(registry, notes_csv)

    disagreements = []
    for _, row in notes_csv.iterrows():
        note_id = row["note_id"]
        expected = registry[note_id]

        prompt = PROMPT_TEMPLATE.format(note_text=row["note"])
        try:
            predicted = _call_llm(prompt)
        except Exception as exc:
            disagreements.append(
                {"note_id": note_id, "field": "LLM_CALL", "expected": "ok", "predicted": str(exc)}
            )
            continue

        # Compare scope
        try:
            expected_scope = _normalise_scope(expected["scope"])
            predicted_scope = _normalise_scope(predicted.get("scope"))
            if expected_scope != predicted_scope:
                disagreements.append(
                    {
                        "note_id": note_id,
                        "field": "scope",
                        "expected": expected_scope,
                        "predicted": predicted_scope,
                    }
                )
        except Exception as exc:
            disagreements.append(
                {"note_id": note_id, "field": "scope", "expected": expected["scope"], "predicted": f"PARSE_ERROR: {exc}"}
            )

        # Compare dates
        for field in ("effective_from", "effective_to"):
            if predicted.get(field) != expected[field]:
                disagreements.append(
                    {
                        "note_id": note_id,
                        "field": field,
                        "expected": expected[field],
                        "predicted": predicted.get(field),
                    }
                )

        # Compare polarity
        if predicted.get("polarity") != expected["polarity"]:
            disagreements.append(
                {
                    "note_id": note_id,
                    "field": "polarity",
                    "expected": expected["polarity"],
                    "predicted": predicted.get("polarity"),
                }
            )

    return disagreements


def main() -> None:
    print(f"Cross-checking notes registry against {OLLAMA_MODEL} at {OLLAMA_URL}")
    disagreements = cross_check()

    if not disagreements:
        print("\nNo disagreements found. The LLM agrees with the curated YAML on all fields.")
        return

    print(f"\n{len(disagreements)} disagreement(s) found (YAML is authoritative):\n")
    for d in disagreements:
        print(f"  {d['note_id']} | {d['field']}")
        print(f"    YAML: {d['expected']!r}")
        print(f"    LLM:  {d['predicted']!r}")

    print("\nRecord these disagreements in README.md under 'LLM cross-check findings'.")


if __name__ == "__main__":
    main()
