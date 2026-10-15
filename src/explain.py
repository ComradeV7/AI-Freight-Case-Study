"""Generate plain-English explanations for flagged candidates.

The LLM sees ONLY the FACTS block (route, week_of, cost_per_tonne_km,
pct_vs_history, pct_vs_peers, VERDICT, MATCHED_NOTE, CLOSEST_NOTE).
It never sees or sets flagged / matched_note_id; those come from src/gate.py.

Resolution order (in src/llm_client.py): cache hit -> live API only when
live=True -> deterministic template.  The network is never touched without
live=True.  Config lives in config/params.yaml (llm section); the API key is
read only from the LLM_API_KEY environment variable.
"""

import os
import sys
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_client import (
    DEFAULT_CACHE_PATH,
    NOCACHE_CACHE_PATH,
    USAGE_LOG_PATH,
    LLMClient,
    load_llm_config,
)


SYSTEM_PROMPT = (
    "You write one short explanation for a freight-cost alert. "
    "Use ONLY the FACTS. Never invent causes, dates or note ids. "
    "Do NOT output raw decimal numbers or percentages. "
    "Follow the INSTRUCTION field exactly. "
    'Reply as JSON {"reason": "<=55 words, plain English"}.'
)


# ---------------------------------------------------------------------------
# FACTS construction
# ---------------------------------------------------------------------------
# Models often emit typographic punctuation (non-breaking hyphens in dates,
# en/em dashes, curly quotes).  The deliverable CSV must stay plain ASCII like
# data/sample_output_format_v2.csv, so normalize those characters.
_UNICODE_TO_ASCII = str.maketrans(
    {
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2015": "-",  # horizontal bar
        "\u2212": "-",  # minus sign
        "\u2043": "-",  # hyphen bullet
        "\u00a0": " ",  # non-breaking space
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
    }
)


def _ascii_clean(text: str) -> str:
    """Normalize typographic Unicode punctuation to ASCII equivalents."""
    if not text:
        return text
    return text.translate(_UNICODE_TO_ASCII)


def _note_id(note: dict | None) -> str:
    """Note id from either the trace schema (note_id) or the registry schema (id)."""
    if not note:
        return ""
    return note.get("id") or note.get("note_id") or ""


def _note_date(note: dict | None) -> str:
    if not note:
        return ""
    return note.get("date") or note.get("effective_from") or ""


_REGISTRY_CACHE: dict | None = None


def _note_registry() -> dict:
    """Lazy-load the curated notes registry (id -> entry) for closest-note detail."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        from src.notes import load_notes_registry

        _REGISTRY_CACHE = load_notes_registry()
    return _REGISTRY_CACHE


def _enrich_note(note: dict | None) -> dict | None:
    """Normalize a retrieval-trace note (note_id/score/polarity) to the
    explain-layer schema (id/date/source_text) using the notes registry."""
    if not note:
        return None
    note_id = _note_id(note)
    entry = _note_registry().get(note_id, {}) if note_id else {}
    return {
        "id": note_id,
        "date": _note_date(note) or entry.get("effective_from", ""),
        "source_text": note.get("source_text") or entry.get("source_text", ""),
        "polarity": note.get("polarity") or entry.get("polarity", ""),
    }


def _instruction(verdict: str, matched_note: dict | None, closest_note: dict | None) -> str:
    """Per-verdict directive embedded in the FACTS block (the user prompt).

    The validator (validate_reason) requires a JUSTIFIED reason to cite the
    matched note id and date, so the instruction states that requirement
    explicitly instead of hoping the model infers it.
    """
    if verdict == "JUSTIFIED":
        note_id = _note_id(matched_note)
        note_date = _note_date(matched_note)
        return (
            f'You MUST start your reason with: "Matches note {note_id} dated {note_date}: " '
            "followed by a brief summary of why it explains the cost rise."
        )
    instruction = (
        "State clearly that no supporting note explains the cost rise and it is "
        "flagged for human review. Do NOT output raw decimal numbers or percentages."
    )
    if closest_note:
        closest_id = _note_id(closest_note)
        closest_date = _note_date(closest_note)
        instruction += (
            f' If CLOSEST_NOTE is present, you may mention "{closest_id} ({closest_date})" '
            "only to state why it does not justify a cost rise on this route/week."
        )
    return instruction


def build_facts(
    route: str,
    week_of: str,
    cost: float,
    pct_vs_history: float,
    pct_vs_peers: float,
    matched_note: dict | None,
    closest_note: dict | None,
) -> dict:
    """Construct the FACTS JSON sent to the LLM (and nothing else).

    Cost and percentage numbers are deliberately NOT exposed to the LLM.
    The sample output reasons never quote them; exposing rounded strings
    still lets a model hallucinate hidden digits, and exposing raw floats
    makes it trivial to invent numbers.  Only note metadata plus an explicit
    per-verdict INSTRUCTION is needed to write a safe justification.  The
    cost/pct arguments are kept for call-site compatibility but unused.
    """
    verdict = "JUSTIFIED" if matched_note else "UNEXPLAINED"
    return {
        "route": route,
        "week_of": week_of,
        "VERDICT": verdict,
        "MATCHED_NOTE": matched_note,
        "CLOSEST_NOTE": closest_note,
        "INSTRUCTION": _instruction(verdict, matched_note, closest_note),
    }


# ---------------------------------------------------------------------------
# Validator (applied to every response, live or cached)
# ---------------------------------------------------------------------------
def _extract_note_ids(text: str) -> list[str]:
    import re

    return re.findall(r"N\d{3,}", text)


def _format_number(value: float) -> str:
    s = f"{value:.10f}".rstrip("0").rstrip(".")
    return s


def _extract_numbers(text: str, exclude_ids: list[str]) -> set[str]:
    """Normalized numeric strings in text, excluding digits inside note ids.

    Percentages are normalized to decimals so that "29.5%" matches FACTS 0.295.
    """
    import re

    scrubbed = text
    for note_id in exclude_ids:
        scrubbed = scrubbed.replace(note_id, "")

    numbers: set[str] = set()
    for match in re.findall(r"\d+(?:\.\d+)?%?", scrubbed):
        if match.endswith("%"):
            try:
                numbers.add(_format_number(float(match[:-1]) / 100.0))
            except ValueError:
                numbers.add(match)
        else:
            numbers.add(match)
            try:
                numbers.add(_format_number(float(match) * 100.0) + "%")
            except ValueError:
                pass
    return numbers


def _numbers_in_facts(facts: dict) -> set[str]:
    import json
    import re

    facts_text = json.dumps(facts, ensure_ascii=True)
    numbers: set[str] = set()
    for match in re.findall(r"\d+(?:\.\d+)?%?", facts_text):
        if match.endswith("%"):
            try:
                numbers.add(_format_number(float(match[:-1]) / 100.0))
            except ValueError:
                numbers.add(match)
        else:
            numbers.add(match)
            try:
                numbers.add(_format_number(float(match) * 100.0) + "%")
            except ValueError:
                pass
    return numbers


def _allowed_note_ids(facts: dict) -> set[str]:
    ids = set()
    for key in ("MATCHED_NOTE", "CLOSEST_NOTE"):
        note_id = _note_id(facts.get(key))
        if note_id:
            ids.add(note_id)
    return ids


def validate_reason(reason: str, facts: dict) -> None:
    """Raise ValueError unless the reason uses only information from FACTS.

    Cost and percentage numbers are no longer passed in FACTS, so the
    validator no longer rejects numbers.  It only guards note citations and
    prevents an UNEXPLAINED verdict from inventing a cause.
    """
    verdict = facts.get("VERDICT", "UNEXPLAINED")
    note_ids_in_text = _extract_note_ids(reason)
    allowed_ids = _allowed_note_ids(facts)

    for note_id in note_ids_in_text:
        if note_id not in allowed_ids:
            raise ValueError(f"Reason cites disallowed note id {note_id}")

    if verdict == "JUSTIFIED":
        matched = facts.get("MATCHED_NOTE") or {}
        matched_id = matched.get("id")
        matched_date = matched.get("date")
        if not matched_id or not matched_date:
            raise ValueError("VERDICT is JUSTIFIED but MATCHED_NOTE is missing")
        if matched_id not in note_ids_in_text:
            raise ValueError(f"Justified reason must cite matched note id {matched_id}")
        if matched_date not in reason:
            raise ValueError(f"Justified reason must contain matched note date {matched_date}")

    if verdict == "UNEXPLAINED":
        # UNEXPLAINED must claim no cause.  Citing only CLOSEST_NOTE is allowed
        # (to say it does not describe a cost rise); other ids are blocked above.
        causal_phrases = ["because", "due to", "caused by", "as a result of"]
        lowered = reason.lower()
        for phrase in causal_phrases:
            if phrase in lowered:
                if "not" in lowered:
                    continue
                raise ValueError(f"Unexplained reason appears to claim a cause ('{phrase}')")


# ---------------------------------------------------------------------------
# Deterministic template (the safe fallback; never cached)
# ---------------------------------------------------------------------------
def _fallback_reason(facts: dict) -> str:
    verdict = facts.get("VERDICT", "UNEXPLAINED")
    if verdict == "JUSTIFIED":
        matched = facts.get("MATCHED_NOTE") or {}
        note_id = matched.get("id", "")
        date = matched.get("date", "")
        source = matched.get("source_text", "")
        words = source.split()
        truncated = " ".join(words[:20]) + ("..." if len(words) > 20 else "")
        return f"Matches note {note_id} dated {date}: {truncated}"
    return (
        "No supporting note was found for this route or date range. "
        "The cost rise is worth a human review."
    )


# ---------------------------------------------------------------------------
# Client construction and candidate loop
# ---------------------------------------------------------------------------
def make_client(
    *,
    live: bool = False,
    use_cache: bool = True,
    no_cache_dir: bool = False,
    cache_path: Path | str | None = None,
    usage_log_path: Path | str | None = None,
    cfg: dict | None = None,
    key: str | None = None,
) -> LLMClient:
    cfg = cfg if cfg is not None else load_llm_config()
    # IGNORE_LLM_CACHE=1 bypasses the shared cache entirely (and stops writing
    # to it), for forced-live / forced-template runs.
    if os.environ.get("IGNORE_LLM_CACHE") == "1":
        use_cache = False
    if cache_path is None:
        cache_path = NOCACHE_CACHE_PATH if no_cache_dir else DEFAULT_CACHE_PATH
    if usage_log_path is None:
        usage_log_path = USAGE_LOG_PATH
    return LLMClient(
        cfg,
        validate_reason,
        _fallback_reason,
        live=live,
        use_cache=use_cache,
        cache_path=cache_path,
        usage_log_path=usage_log_path,
        key=key,
    )


_FALLBACK_NOTICE_SHOWN = False


def _notify_fallback_once() -> None:
    """Print a single clean notice when the live LLM is unavailable/invalid.

    The pipeline never crashes on an unreachable endpoint: every row falls back
    to the deterministic template.  One line (not one per row) keeps output
    readable on a reviewer's machine with no Ollama/API running.
    """
    global _FALLBACK_NOTICE_SHOWN
    if not _FALLBACK_NOTICE_SHOWN:
        print(
            "[explain] Live LLM unavailable or response invalid; "
            "using deterministic template fallback."
        )
        _FALLBACK_NOTICE_SHOWN = True


def explain_candidates(
    candidates: pd.DataFrame,
    retrieval_trace: list[dict] | None = None,
    *,
    client: LLMClient | None = None,
    live: bool = False,
    use_cache: bool = True,
    no_cache_dir: bool = False,
    temperature=None,
) -> pd.DataFrame:
    """Add a validated reason column to the gated candidates dataframe."""
    if client is None:
        client = make_client(
            live=live,
            use_cache=use_cache,
            no_cache_dir=no_cache_dir,
        )

    # Map retrieval trace to closest note per candidate.
    closest_by_key = {}
    if retrieval_trace:
        for item in retrieval_trace:
            key = (item["route"], item["week_of"])
            top = item.get("top_3", [])
            if top:
                closest_by_key[key] = top[0]

    reasons = []
    for _, row in candidates.iterrows():
        route = row["route"]
        week_of = (
            row["week_of"].strftime("%Y-%m-%d")
            if isinstance(row["week_of"], pd.Timestamp)
            else str(row["week_of"])
        )
        matched = None
        if row.get("matched_note_id"):
            matched = {
                "id": row["matched_note_id"],
                "date": row.get("matched_note_date", ""),
                "source_text": row.get("matched_note_text", ""),
                "window": row.get("matched_note_window", ""),
            }
        closest = _enrich_note(closest_by_key.get((route, week_of)))
        facts = build_facts(
            route=route,
            week_of=week_of,
            cost=row["cost_per_tonne_km"],
            pct_vs_history=row["vs_own_history"],
            pct_vs_peers=row["vs_similar_routes"],
            matched_note=matched,
            closest_note=closest,
        )
        result = client.resolve(facts, SYSTEM_PROMPT, temperature=temperature)
        if result.get("source") == "template" and client.live:
            _notify_fallback_once()
        reasons.append(_ascii_clean(result["reason"]))

    df = candidates.copy()
    df["reason"] = reasons
    return df
