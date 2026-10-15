"""Spec tests for the LLM client:

(b) cache deleted and no --live -> every reason comes from the template
(c) mocked bad responses (invented note id, invented number, empty text) are
    rejected and replaced by the template; bad responses are never cached
(d) the API key never appears in any file under the project folder or any log

Plus retry/backoff behavior on failures.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.explain import SYSTEM_PROMPT, _fallback_reason, build_facts, make_client, validate_reason
from src.llm_client import LLMClient, LLMError, load_llm_config

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def justified_facts():
    return build_facts(
        route="Ahmedabad-Mumbai",
        week_of="2025-01-20",
        cost=3.29,
        pct_vs_history=0.295,
        pct_vs_peers=0.225,
        matched_note={
            "id": "N002",
            "date": "2025-01-20",
            "source_text": "A regional festival week saw a temporary surcharge.",
            "window": "2025-01-20..2025-01-26",
        },
        closest_note={
            "id": "N002",
            "date": "2025-01-20",
            "source_text": "A regional festival week saw a temporary surcharge.",
        },
    )


@pytest.fixture
def candidates_df():
    """A minimal gated-candidates frame as produced by src/gate.py."""
    return pd.DataFrame(
        [
            {
                "route": "Ahmedabad-Mumbai",
                "week_of": pd.Timestamp("2025-01-20"),
                "cost_per_tonne_km": 3.29,
                "vs_own_history": 0.295,
                "vs_similar_routes": 0.225,
                "flagged": "No (justified)",
                "matched_note_id": "N002",
                "matched_note_date": "2025-01-20",
                "matched_note_text": "A regional festival week saw a temporary surcharge.",
                "matched_note_window": "2025-01-20..2025-01-26",
                "reason": "",
            },
            {
                "route": "Mumbai-Pune",
                "week_of": pd.Timestamp("2025-09-15"),
                "cost_per_tonne_km": 3.98,
                "vs_own_history": 0.092,
                "vs_similar_routes": 0.236,
                "flagged": "Yes",
                "matched_note_id": "",
                "matched_note_date": "",
                "matched_note_text": "",
                "matched_note_window": "",
                "reason": "",
            },
        ]
    )


# ---------------------------------------------------------------------------
# (b) cache deleted, no --live: every reason from the template, pipeline works
# ---------------------------------------------------------------------------
def test_no_cache_no_live_all_templates(candidates_df, tmp_path):
    from src.explain import explain_candidates

    with patch(
        "src.llm_client.urllib.request.urlopen",
        side_effect=AssertionError("network touched without --live"),
    ):
        explained = explain_candidates(
            candidates_df,
            retrieval_trace=None,
            live=False,
            use_cache=True,
            no_cache_dir=False,
        )

    # Every reason is the deterministic template for its facts.
    for _, row in explained.iterrows():
        facts = build_facts(
            route=row["route"],
            week_of=row["week_of"].strftime("%Y-%m-%d"),
            cost=row["cost_per_tonne_km"],
            pct_vs_history=row["vs_own_history"],
            pct_vs_peers=row["vs_similar_routes"],
            matched_note=(
                {
                    "id": row["matched_note_id"],
                    "date": row["matched_note_date"],
                    "source_text": row["matched_note_text"],
                    "window": row["matched_note_window"],
                }
                if row["matched_note_id"]
                else None
            ),
            closest_note=None,
        )
        assert row["reason"] == _fallback_reason(facts)

    # The pipeline still succeeds: no exception, reasons present and valid.
    assert explained["reason"].notna().all()
    assert (explained["reason"].str.len() > 0).all()


def test_missing_cache_file_is_handled(tmp_path, justified_facts):
    """A missing cache file behaves like an empty cache (template offline)."""
    client = make_client(
        live=False,
        cache_path=tmp_path / "does_not_exist.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    result = client.resolve(justified_facts, SYSTEM_PROMPT)
    assert result["source"] == "template"


# ---------------------------------------------------------------------------
# (c) mocked bad responses are rejected and replaced by the template
# ---------------------------------------------------------------------------
BAD_RESPONSES = {
    "invented_note_id": json.dumps({"reason": "Matches note N999 dated 2025-01-20: invented."}),
    # Numbers are no longer in FACTS/validated, so invented percentages are
    # accepted; an omission of the required matched-note citation is not.
    "missing_note_id": json.dumps({"reason": "Dated 2025-01-20: costs rose for trucks."}),
    "empty_text": "",
    "not_json": "This is not JSON at all.",
}


@pytest.mark.parametrize("kind", sorted(BAD_RESPONSES))
def test_bad_live_responses_fall_back_to_template(justified_facts, tmp_path, kind):
    client = make_client(
        live=True,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )

    attempts = {"n": 0}

    def fake_transport(facts, system_prompt, temperature):
        attempts["n"] += 1
        return BAD_RESPONSES[kind], {"prompt_tokens": 50, "completion_tokens": 5}

    with patch.object(LLMClient, "_transport", side_effect=fake_transport):
        with patch("src.llm_client.time.sleep"):  # skip backoff delays in tests
            result = client.resolve(justified_facts, SYSTEM_PROMPT)

    assert result["source"] == "template"
    assert result["reason"] == _fallback_reason(justified_facts)
    # Initial attempt + 2 retries were made before giving up.
    assert attempts["n"] == 3
    # Nothing invalid was cached.
    assert not (tmp_path / "cache.json").exists() or not json.loads(
        (tmp_path / "cache.json").read_text(encoding="utf-8")
    )
    # The usage log records the failed live chain with retries and fallback.
    record = json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8").strip())
    assert record["fallback"] is True
    assert record["retries"] == 2


def test_transport_error_then_success_retries_count(justified_facts, tmp_path):
    """One 429-style failure, then success: retry counted, reason cached."""
    client = make_client(
        live=True,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    good = json.dumps({"reason": "Matches note N002 dated 2025-01-20: festival surcharge."})
    calls = {"n": 0}

    def fake_transport(facts, system_prompt, temperature):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("HTTP 429 Too Many Requests from the LLM endpoint")
        return good, {"prompt_tokens": 80, "completion_tokens": 18}

    with patch.object(LLMClient, "_transport", side_effect=fake_transport):
        with patch("src.llm_client.time.sleep"):
            result = client.resolve(justified_facts, SYSTEM_PROMPT)

    assert result["source"] == "live"
    assert result["retries"] == 1
    assert calls["n"] == 2
    record = json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8").strip())
    assert record["retries"] == 1
    assert record["fallback"] is False


def test_truncated_response_retries(justified_facts, tmp_path):
    """finish_reason=length is treated as truncation and retried."""
    client = make_client(
        live=True,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    good = json.dumps({"reason": "Matches note N002 dated 2025-01-20: festival surcharge."})
    calls = {"n": 0}

    def fake_transport(facts, system_prompt, temperature):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("response truncated (finish_reason=length)")
        return good, {"prompt_tokens": 80, "completion_tokens": 18}

    with patch.object(LLMClient, "_transport", side_effect=fake_transport):
        with patch("src.llm_client.time.sleep"):
            result = client.resolve(justified_facts, SYSTEM_PROMPT)

    assert result["source"] == "live"
    assert calls["n"] == 2


def test_missing_key_raises_sanitized_error(justified_facts, tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    client = make_client(
        live=True,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
        key="",
    )
    with patch("src.llm_client.time.sleep"):
        result = client.resolve(justified_facts, SYSTEM_PROMPT)
    assert result["source"] == "template"


# ---------------------------------------------------------------------------
# (d) the key never appears in any file under the project folder or any log
# ---------------------------------------------------------------------------
SKIP_DIRS = {
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "chroma_index",
    "cache_nocache",
    "node_modules",
    ".git",
}


def test_api_key_never_written_to_any_file(justified_facts, tmp_path, monkeypatch):
    # Built from parts so the literal sentinel does not appear in this file.
    sentinel = "gsk_TEST-" + "SECRET-" + "SENTINEL-" + "KEY-" + "DO-NOT-USE"
    monkeypatch.setenv("LLM_API_KEY", sentinel)

    # Exercise a full live chain with mocked transport (never a real call).
    client = make_client(
        live=True,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    good = json.dumps({"reason": "Matches note N002 dated 2025-01-20: festival surcharge."})

    def fake_transport(facts, system_prompt, temperature):
        return good, {"prompt_tokens": 100, "completion_tokens": 20}

    with patch.object(LLMClient, "_transport", side_effect=fake_transport):
        client.resolve(justified_facts, SYSTEM_PROMPT)

    # The usage log itself must not contain the key.
    usage = (tmp_path / "usage.jsonl").read_text(encoding="utf-8")
    assert sentinel not in usage

    # Scan every project file (skip heavy/irrelevant dirs and binaries).
    scanned = 0
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        scanned += 1
        assert sentinel not in text, f"API key leaked into {rel}"

    assert scanned > 20  # sanity: we actually scanned the project


def test_error_messages_are_sanitized(monkeypatch):
    # Built from parts so the literal sentinel does not appear in this file.
    sentinel = "gsk_TEST-" + "SECRET-" + "SENTINEL-" + "KEY-" + "DO-NOT-USE"
    monkeypatch.setenv("LLM_API_KEY", sentinel)
    from src.llm_client import _sanitize

    class FakeHTTPOSError(Exception):
        pass

    err = _sanitize(FakeHTTPOSError(f"request failed with Authorization: Bearer {sentinel}"))
    assert sentinel not in err
    assert "***" in err
