"""Stretch-goal Q&A assistant (grounded, deterministic).

Usage:  python src/qa.py "why did Chennai-Bangalore get pricier in March?"

The assistant is deterministic by design: it answers ONLY from verified pipeline
results (``outputs/flagged_routes.csv``) plus the raw shipment data, and refuses
anything it cannot ground.  This is the anti-hallucination guarantee the brief
asks for.  An optional ``--live`` flag can rephrase an already-computed answer
with the configured LLM, but it strictly falls back to the deterministic text if
the model is offline or the rephrase introduces ungrounded numbers/note ids.
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.business import excess_spend, inr, transporter_drilldown, weekly_with_baselines
from src.load import load_shipments


PROJECT_ROOT = Path(__file__).parent.parent
FLAGGED_PATH = PROJECT_ROOT / "outputs" / "flagged_routes.csv"
NOTES_PATH = PROJECT_ROOT / "data" / "context_notes.csv"

NO_FINDING = "I don't have a finding for that route/period in flagged_routes.csv."

KNOWN_ROUTES = [
    "Ahmedabad-Mumbai",
    "Chennai-Bangalore",
    "Delhi-Chennai",
    "Delhi-Jaipur",
    "Kolkata-Bhubaneswar",
    "Mumbai-Delhi",
    "Mumbai-Pune",
]
KNOWN_CITIES = sorted(
    {city.lower() for route in KNOWN_ROUTES for city in route.split("-")}
)

_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


# ---------------------------------------------------------------------------
# Question parsing
# ---------------------------------------------------------------------------
def resolve_routes(question: str) -> tuple[list[str], bool]:
    """Return (routes, is_unknown_route).

    Unknown hyphenated route tokens (e.g. 'Hyderabad-Bangalore') are treated as
    an unknown route so we refuse rather than guess.
    """
    text = question.lower()
    known = {r.lower(): r for r in KNOWN_ROUTES}

    for token in re.findall(r"[a-z]+-[a-z]+", text):
        if token in known:
            return [known[token]], False
        # A route-looking token that is not in the dataset.
        return [], True

    city_hits = [c for c in KNOWN_CITIES if re.search(rf"\b{c}\b", text)]
    if city_hits:
        routes = [
            r for r in KNOWN_ROUTES if any(c in r.lower() for c in city_hits)
        ]
        return routes, False

    return [], False


def parse_period(question: str) -> tuple[int | None, int | None]:
    """Return (month, year) detected in the question, each optional."""
    text = question.lower()
    month = None
    for name, number in _MONTHS.items():
        if re.search(rf"\b{name}\b", text):
            month = number
            break
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None
    return month, year


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def _load_flagged(path: Path) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python src/main.py` first to produce it."
        )
    df = pd.read_csv(path)
    df["week_of"] = pd.to_datetime(df["week_of"])
    return df


def _note_texts(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    df = pd.read_csv(path)
    return {str(r["note_id"]): str(r["note"]) for _, r in df.iterrows()}


def _first_sentence(text: str, limit: int = 160) -> str:
    sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return sentence[:limit]


def _excess_by_week(shipments: pd.DataFrame) -> dict:
    weekly = excess_spend(weekly_with_baselines(shipments))
    return {
        (row["route"], row["week_of"]): row["excess_inr"]
        for _, row in weekly.iterrows()
    }


# ---------------------------------------------------------------------------
# Answer generation (deterministic, grounded)
# ---------------------------------------------------------------------------
def _route_answer(
    route: str,
    rows: pd.DataFrame,
    note_texts: dict,
    shipments: pd.DataFrame,
    excess: dict,
) -> str:
    rows = rows.sort_values("week_of")
    justified = rows[rows["flagged"] == "No (justified)"]
    unexplained = rows[rows["flagged"] == "Yes"]

    parts = [f"{route}:"]

    for _, r in justified.iterrows():
        note_id = r["matched_note_id"]
        note = _first_sentence(note_texts.get(note_id, ""))
        detail = f" - {note}" if note else ""
        parts.append(
            f"  - {r['week_of'].date()} was JUSTIFIED by note {note_id}{detail}"
        )

    if not unexplained.empty:
        weeks = ", ".join(str(r["week_of"].date()) for _, r in unexplained.iterrows())
        leak = sum(
            excess.get((r["route"], r["week_of"]), 0.0)
            for _, r in unexplained.iterrows()
        )
        parts.append(
            f"  - {weeks} are UNEXPLAINED (no supporting note; flagged for review)."
        )
        parts.append(f"  - Estimated unexplained overcharge on those weeks: {inr(leak)}.")

        for _, r in unexplained.iterrows():
            drill = transporter_drilldown(shipments, route, r["week_of"])
            movers = sorted(
                [d for d in drill if d.get("delta_pct") is not None],
                key=lambda d: d["delta_pct"],
                reverse=True,
            )
            if movers:
                top = ", ".join(
                    f"{d['transporter']} {d['delta_pct']:+.1%}" for d in movers[:3]
                )
                parts.append(
                    f"  - Transporter check for {r['week_of'].date()} (vs each carrier's "
                    f"own 8-week average): {top}."
                )

    if not justified.empty and unexplained.empty:
        parts.append("  - No unexplained weeks found for this filter.")

    return "\n".join(parts)


def _overall_answer(
    rows: pd.DataFrame, excess: dict
) -> str:
    lines = ["All flagged route-weeks in outputs/flagged_routes.csv:"]
    for _, r in rows.sort_values(["week_of", "route"]).iterrows():
        note = f" (note {r['matched_note_id']})" if r["matched_note_id"] else ""
        lines.append(
            f"  - {r['route']} {r['week_of'].date()}: {r['flagged']}{note}"
        )
    return "\n".join(lines)


def answer(question: str, flagged_path: Path | str | None = None) -> str:
    """Return a grounded, deterministic answer for ``question``."""
    flagged = _load_flagged(Path(flagged_path) if flagged_path else FLAGGED_PATH)
    note_texts = _note_texts(NOTES_PATH)

    routes, unknown = resolve_routes(question)
    if unknown:
        return NO_FINDING

    month, year = parse_period(question)

    rows = flagged
    if routes:
        rows = rows[rows["route"].isin(routes)]
    if month is not None:
        rows = rows[rows["week_of"].dt.month == month]
    if year is not None:
        rows = rows[rows["week_of"].dt.year == year]

    if rows.empty:
        return NO_FINDING

    shipments = load_shipments()
    excess = _excess_by_week(shipments)

    if not routes:
        return _overall_answer(rows, excess)

    blocks = [
        _route_answer(route, rows[rows["route"] == route], note_texts, shipments, excess)
        for route in routes
        if not rows[rows["route"] == route].empty
    ]
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Optional LLM rephrase (off by default; never changes the grounded facts)
# ---------------------------------------------------------------------------
def _polish(grounded: str) -> str:
    """Rephrase ``grounded`` with the configured LLM; fall back on any issue.

    Safety: every number and note id in the rephrase must already appear in the
    deterministic answer, otherwise the rephrase is rejected.
    """
    try:
        from src.llm_client import LLMClient, load_llm_config

        grounded_tokens = set(re.findall(r"\d+(?:\.\d+)?%?|N\d{3,}", grounded))

        def _validate(reason: str, facts: dict) -> None:
            for token in re.findall(r"\d+(?:\.\d+)?%?|N\d{3,}", reason):
                if token not in grounded_tokens:
                    raise ValueError(f"ungrounded token {token!r}")

        cfg = load_llm_config()
        client = LLMClient(cfg, _validate, lambda facts: grounded)
        facts = {
            "INSTRUCTION": "Rephrase the ANSWER without adding facts.",
            "ANSWER": grounded,
        }
        result = client.resolve(
            facts, "You only rephrase. Never add numbers or note ids."
        )
        return result["reason"]
    except Exception:
        return grounded


def main() -> None:
    # The report text contains the rupee sign; make the Windows console safe.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Grounded FreightTiger Q&A assistant")
    parser.add_argument("question", help="Natural-language question about the findings")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Opt in to LLM rephrasing (deterministic fallback always available).",
    )
    args = parser.parse_args()

    text = answer(args.question)
    if args.live and text != NO_FINDING:
        text = _polish(text)
    print(text)


if __name__ == "__main__":
    main()
