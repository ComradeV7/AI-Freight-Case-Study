"""Shared test fixtures.

The LLM config accepts environment overrides (LLM_PROVIDER, OLLAMA_MODEL,
OPENAI_MODEL, LLM_BASE_URL, OLLAMA_TEMPERATURE, OLLAMA_SEED) as a documented
feature.  That makes tests environment-sensitive: a developer shell or the
reproducibility harness may export these variables, which would silently
change provider/model expectations.

This autouse fixture clears those variables for every test so the suite is
hermetic regardless of the ambient shell.  Tests that want to exercise the
overrides set them explicitly with monkeypatch.
"""

import pytest

_LLM_CONFIG_ENV = (
    "LLM_PROVIDER",
    "OPENAI_MODEL",
    "OLLAMA_MODEL",
    "LLM_BASE_URL",
    "OLLAMA_TEMPERATURE",
    "OLLAMA_SEED",
)


@pytest.fixture(autouse=True)
def _isolate_llm_config_env(monkeypatch):
    for name in _LLM_CONFIG_ENV:
        monkeypatch.delenv(name, raising=False)
    yield
