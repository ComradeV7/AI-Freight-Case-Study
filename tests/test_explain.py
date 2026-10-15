"""Tests for the explain layer: FACTS, validator, template, cache/live resolution."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.explain import (
    SYSTEM_PROMPT,
    _fallback_reason,
    build_facts,
    explain_candidates,
    make_client,
    validate_reason,
)
from src.llm_client import LLMClient, load_llm_config


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
def unexplained_facts():
    return build_facts(
        route="Mumbai-Pune",
        week_of="2025-09-15",
        cost=3.98,
        pct_vs_history=0.092,
        pct_vs_peers=0.236,
        matched_note=None,
        closest_note={
            "id": "N006",
            "date": "2025-09-22",
            "source_text": "Demand remained stable with no major disruptions.",
        },
    )


# ---------------------------------------------------------------------------
# FACTS block
# ---------------------------------------------------------------------------
def test_build_facts(justified_facts):
    assert justified_facts["route"] == "Ahmedabad-Mumbai"
    assert justified_facts["week_of"] == "2025-01-20"
    assert justified_facts["VERDICT"] == "JUSTIFIED"
    assert justified_facts["MATCHED_NOTE"]["id"] == "N002"
    # Cost and percentages are deliberately withheld from the LLM FACTS block.
    assert "cost_per_tonne_km" not in justified_facts
    assert "pct_vs_history" not in justified_facts
    assert "pct_vs_peers" not in justified_facts


def test_build_facts_unexplained(unexplained_facts):
    assert unexplained_facts["VERDICT"] == "UNEXPLAINED"
    assert unexplained_facts["MATCHED_NOTE"] is None
    assert unexplained_facts["CLOSEST_NOTE"]["id"] == "N006"


# ---------------------------------------------------------------------------
# Validator (applies to every response, live or cached)
# ---------------------------------------------------------------------------
def test_validate_reason_justified_ok(justified_facts):
    reason = "Matches note N002 dated 2025-01-20: a regional festival surcharge applied."
    validate_reason(reason, justified_facts)


def test_validate_reason_justified_missing_note_id(justified_facts):
    reason = "Dated 2025-01-20: a regional festival surcharge applied."
    with pytest.raises(ValueError, match="matched note id"):
        validate_reason(reason, justified_facts)


def test_validate_reason_justified_missing_date(justified_facts):
    reason = "Matches note N002: a regional festival surcharge applied."
    with pytest.raises(ValueError, match="matched note date"):
        validate_reason(reason, justified_facts)


def test_validate_reason_unexplained_with_cause(unexplained_facts):
    reason = "The rise was caused by N006."
    with pytest.raises(ValueError, match="claim a cause"):
        validate_reason(reason, unexplained_facts)


def test_validate_reason_unexplained_citing_closest_ok(unexplained_facts):
    reason = (
        "No supporting note was found. The rise is worth human review. "
        "N006 does not describe a cost rise for this route or time."
    )
    validate_reason(reason, unexplained_facts)


def test_validate_reason_rejects_disallowed_note_id(unexplained_facts):
    reason = "The rise was explained by N003."
    with pytest.raises(ValueError, match="disallowed note id"):
        validate_reason(reason, unexplained_facts)


def test_reason_ascii_normalization():
    """Typographic punctuation from the model is normalized to ASCII for the CSV."""
    from src.explain import _ascii_clean

    assert _ascii_clean("2024\u201102\u201105 \u2013 flagged\u2019") == "2024-02-05 - flagged'"
    assert _ascii_clean("a\u00a0b \u2026 \"x\"") == 'a b ... "x"'
    assert _ascii_clean("") == ""


def test_closest_note_from_trace_schema_is_allowed(unexplained_facts):
    """Retrieval-trace closest notes use `note_id`; citing them must be allowed."""
    from src.explain import _enrich_note

    enriched = _enrich_note(
        {"note_id": "N007", "score": 0.63, "polarity": "informational"}
    )
    assert enriched["id"] == "N007"
    assert enriched["date"]  # pulled from the notes registry
    assert "road" in enriched["source_text"].lower()

    facts = build_facts(
        route="Delhi-Jaipur",
        week_of="2024-11-18",
        cost=4.09,
        pct_vs_history=0.276,
        pct_vs_peers=0.197,
        matched_note=None,
        closest_note=enriched,
    )
    reason = (
        "No supporting note explains the cost rise. "
        f"N007 ({enriched['date']}) does not justify a cost rise on this route/week."
    )
    validate_reason(reason, facts)


def test_validate_reason_allows_numbers_not_in_facts(unexplained_facts):
    # Numbers are no longer in FACTS, so the validator only enforces note ids
    # and causal claims.  A reason with arbitrary percentages must pass.
    reason = "No supporting note was found; the rise was 44.4% and worth review."
    validate_reason(reason, unexplained_facts)


def test_validate_reason_rejects_empty(justified_facts):
    with pytest.raises(Exception):
        validate_reason("", justified_facts)


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------
def test_template_justified(justified_facts):
    reason = _fallback_reason(justified_facts)
    assert "N002" in reason
    assert "2025-01-20" in reason


def test_template_unexplained(unexplained_facts):
    reason = _fallback_reason(unexplained_facts)
    assert "No supporting note was found" in reason
    validate_reason(reason, unexplained_facts)


def test_reason_word_limit():
    """Template reasons stay within the <=55 word budget."""
    facts = build_facts(
        route="Test-Route",
        week_of="2025-01-20",
        cost=3.0,
        pct_vs_history=0.1,
        pct_vs_peers=0.1,
        matched_note={
            "id": "N001",
            "date": "2025-01-20",
            "source_text": " ".join(["word"] * 100),
            "window": "2025-01-20..2025-01-26",
        },
        closest_note=None,
    )
    assert len(_fallback_reason(facts).split()) <= 55


# ---------------------------------------------------------------------------
# Resolution: cache -> live (opt-in) -> template
# ---------------------------------------------------------------------------
def test_no_live_never_touches_network(justified_facts, tmp_path):
    """Without live=True the network is never called, cache miss -> template."""
    client = make_client(
        live=False,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    with patch(
        "src.llm_client.urllib.request.urlopen",
        side_effect=AssertionError("network touched without --live"),
    ):
        result = client.resolve(justified_facts, SYSTEM_PROMPT)
    assert result["source"] == "template"
    assert result["reason"] == _fallback_reason(justified_facts)


def test_live_success_is_cached_and_validated(justified_facts, tmp_path):
    """A valid live response is cached; the next offline resolve is a cache hit."""
    client = make_client(
        live=True,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    good = json.dumps({"reason": "Matches note N002 dated 2025-01-20: festival surcharge applied."})

    def fake_transport(facts, system_prompt, temperature):
        return good, {"prompt_tokens": 100, "completion_tokens": 20}

    with patch.object(LLMClient, "_transport", side_effect=fake_transport):
        result = client.resolve(justified_facts, SYSTEM_PROMPT)
    assert result["source"] == "live"

    # Second resolve offline (live=False) must be a cache hit, no network.
    offline = make_client(
        live=False,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    with patch(
        "src.llm_client.urllib.request.urlopen",
        side_effect=AssertionError("network touched without --live"),
    ):
        result2 = offline.resolve(justified_facts, SYSTEM_PROMPT)
    assert result2["source"] == "cache"
    assert result2["reason"] == result["reason"]


def test_invalid_cached_entry_is_treated_as_miss(justified_facts, tmp_path):
    """Cached responses are re-validated; an invalid entry is ignored."""
    from src.llm_client import cache_key, load_llm_config, save_cache

    cfg = load_llm_config()
    key = cache_key(facts=justified_facts, system_prompt=SYSTEM_PROMPT,
                    model=cfg["model"], temperature=cfg["temperature"], seed=cfg["seed"])
    save_cache(tmp_path / "cache.json", {key: {"reason": "Invented cause N999 with 99% rise."}})

    client = make_client(
        live=False,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    result = client.resolve(justified_facts, SYSTEM_PROMPT)
    assert result["source"] == "template"


def test_usage_log_records_live_call_fields(justified_facts, tmp_path):
    """logs/usage.jsonl gets model, prompt_tokens, completion_tokens, cache_hit=false, retries."""
    client = make_client(
        live=True,
        cache_path=tmp_path / "cache.json",
        usage_log_path=tmp_path / "usage.jsonl",
    )
    good = json.dumps({"reason": "Matches note N002 dated 2025-01-20: festival surcharge applied."})

    def fake_transport(facts, system_prompt, temperature):
        return good, {"prompt_tokens": 111, "completion_tokens": 22}

    with patch.object(LLMClient, "_transport", side_effect=fake_transport):
        client.resolve(justified_facts, SYSTEM_PROMPT)

    record = json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8").strip())
    assert record["model"] == client.cfg["model"]
    assert record["prompt_tokens"] == 111
    assert record["completion_tokens"] == 22
    assert record["cache_hit"] is False
    assert record["retries"] == 0


def test_ignore_llm_cache_env_disables_cache(monkeypatch, tmp_path):
    """IGNORE_LLM_CACHE=1 bypasses read/write of the shared cache."""
    from src.explain import make_client

    monkeypatch.setenv("IGNORE_LLM_CACHE", "1")
    client = make_client(cache_path=tmp_path / "cache.json")
    assert client.use_cache is False


def test_config_defaults_from_params_yaml():
    cfg = load_llm_config()
    assert cfg["provider"] == "openai"
    assert cfg["base_url"] == "https://api.groq.com/openai/v1"
    assert cfg["model"] == "openai/gpt-oss-120b"
    assert cfg["temperature"] == 0
    assert cfg["seed"] == 42
    assert cfg["reasoning_effort"] == "low"
    assert cfg["max_completion_tokens"] == 400
    assert cfg["request_spacing_seconds"] == 2


def test_config_env_overrides(monkeypatch):
    """Documented env vars override the YAML config (used by run_3x.ps1)."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.7")
    monkeypatch.setenv("OLLAMA_SEED", "random")
    cfg = load_llm_config()
    assert cfg["provider"] == "ollama"
    assert cfg["model"] == "llama3.2:3b"
    assert cfg["temperature"] == 0.7
    # Non-integer seeds (the temp-0.7 harness run) are passed through verbatim.
    assert cfg["seed"] == "random"
    # Ollama default URL replaces the Groq URL when the provider is switched.
    assert cfg["base_url"] == "http://localhost:11434"


def test_config_env_override_openai_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "openai/gpt-oss-20b")
    cfg = load_llm_config()
    assert cfg["model"] == "openai/gpt-oss-20b"
    assert cfg["base_url"] == "https://api.groq.com/openai/v1"
