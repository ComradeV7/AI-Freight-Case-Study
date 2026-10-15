"""LLM provider interface with three backends: cache (default), live API, template.

Resolution order for every candidate (never touches the network unless live=True):
  1. cache hit (re-validated on read)
  2. live API — only when live=True
  3. deterministic template (never cached)

Config comes from the `llm` section of config/params.yaml.  The API key is read
ONLY from the LLM_API_KEY environment variable; it is never written to any file,
log, or exception message.
"""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))


PROJECT_ROOT = Path(__file__).parent.parent
PARAMS_PATH = PROJECT_ROOT / "config" / "params.yaml"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "llm_cache.json"
NOCACHE_CACHE_PATH = PROJECT_ROOT / "data" / "cache_nocache" / "llm_cache.json"
USAGE_LOG_PATH = PROJECT_ROOT / "logs" / "usage.jsonl"

DEFAULTS = {
    "provider": "openai",
    "base_url": "https://api.groq.com/openai/v1",
    "model": "openai/gpt-oss-120b",
    "temperature": 0,
    "seed": 42,
    "reasoning_effort": "low",
    "max_completion_tokens": 400,
    "request_spacing_seconds": 2,
}

# Initial attempt + up to 2 retries.
MAX_ATTEMPTS = 3

# Groq sits behind Cloudflare, which rejects the default Python-urllib user
# agent with HTTP 403 (error code 1010).  Send a proper user agent.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) freighttiger/1.0"


class LLMError(RuntimeError):
    """Sanitized transport/config error.  Never contains the API key."""


def load_llm_config(params_path: Path | str | None = None) -> dict:
    """Load the llm section of config/params.yaml over DEFAULTS.

    Documented environment variables (see run_3x.ps1 / README) override the
    YAML afterwards so the harness and manual runs can switch models without
    editing files.  The API key is never part of this config.
    """
    cfg = dict(DEFAULTS)
    path = Path(params_path) if params_path else PARAMS_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            params = yaml.safe_load(f) or {}
        llm = params.get("llm") or {}
        for key in DEFAULTS:
            if key in llm:
                cfg[key] = llm[key]

    # Environment overrides (fixed contract used by run_3x.ps1 and README):
    #   LLM_PROVIDER        -> provider        ("openai" | "ollama")
    #   OPENAI_MODEL        -> model           (only when provider=openai)
    #   OLLAMA_MODEL        -> model           (only when provider=ollama)
    #   LLM_BASE_URL        -> base_url
    #   OLLAMA_TEMPERATURE  -> temperature
    #   OLLAMA_SEED         -> seed
    provider = os.environ.get("LLM_PROVIDER")
    if provider:
        cfg["provider"] = provider
    model_var = "OPENAI_MODEL" if cfg["provider"] == "openai" else "OLLAMA_MODEL"
    model = os.environ.get(model_var)
    if model:
        cfg["model"] = model
    base_url = os.environ.get("LLM_BASE_URL")
    if base_url:
        cfg["base_url"] = base_url
    elif cfg["provider"] == "ollama" and "groq.com" in cfg["base_url"]:
        # Ollama transport appends /api/generate to the base URL.
        cfg["base_url"] = "http://localhost:11434"
    temperature = os.environ.get("OLLAMA_TEMPERATURE")
    if temperature not in (None, ""):
        cfg["temperature"] = float(temperature)
    seed = os.environ.get("OLLAMA_SEED")
    if seed not in (None, ""):
        try:
            cfg["seed"] = int(seed)
        except ValueError:
            # The reproducibility harness uses "random" for the temp-0.7 run.
            cfg["seed"] = seed
    return cfg


def cache_key(facts: dict, system_prompt: str, model: str, temperature, seed) -> str:
    """SHA-256(FACTS + system prompt + model + temperature + seed)."""
    payload = (
        json.dumps(facts, sort_keys=True, ensure_ascii=True)
        + system_prompt
        + str(model)
        + str(temperature)
        + str(seed)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cache(path: Path | str) -> dict:
    path = Path(path)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(path: Path | str, cache: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _sanitize(exc: Exception) -> str:
    """Error text guaranteed free of request headers and the API key."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason} from the LLM endpoint"
    text = str(exc)
    key = os.environ.get("LLM_API_KEY", "")
    if key:
        text = text.replace(key, "***")
    return text


class LLMClient:
    """Three backends behind one resolve() call: cache -> live (opt-in) -> template."""

    def __init__(
        self,
        cfg: dict,
        validate,
        template,
        *,
        live: bool = False,
        use_cache: bool = True,
        cache_path: Path | str | None = None,
        usage_log_path: Path | str | None = None,
        key: str | None = None,
    ):
        self.cfg = cfg
        self.validate = validate  # (reason, facts) -> None or raises
        self.template = template  # (facts) -> deterministic reason
        self.live = live
        self.use_cache = use_cache
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
        self.usage_log_path = Path(usage_log_path) if usage_log_path else USAGE_LOG_PATH
        self._key = key if key is not None else os.environ.get("LLM_API_KEY", "")
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Cache backend
    # ------------------------------------------------------------------
    def _cache_get(self, key: str, facts: dict) -> str | None:
        entry = load_cache(self.cache_path).get(key)
        if not entry:
            return None
        # Validator applies to cached responses too; invalid entries are misses.
        try:
            self.validate(entry["reason"], facts)
        except Exception:
            return None
        return entry["reason"]

    def _cache_put(self, key: str, reason: str) -> None:
        cache = load_cache(self.cache_path)
        cache[key] = {
            "reason": reason,
            "model": self.cfg["model"],
            "temperature": self.cfg["temperature"],
            "seed": self.cfg["seed"],
        }
        save_cache(self.cache_path, cache)

    # ------------------------------------------------------------------
    # Live backends
    # ------------------------------------------------------------------
    def _space_requests(self) -> None:
        spacing = float(self.cfg.get("request_spacing_seconds", 2) or 0)
        wait = spacing - (time.monotonic() - self._last_request_time)
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def _call_openai(self, facts: dict, system_prompt: str, temperature) -> tuple[str, dict]:
        """OpenAI-compatible chat completions (e.g., Groq). Returns (content, usage)."""
        if not self._key:
            raise LLMError("LLM_API_KEY environment variable is not set")

        self._space_requests()
        payload = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(facts, indent=2)},
            ],
            "temperature": temperature,
            "max_completion_tokens": int(self.cfg.get("max_completion_tokens", 400)),
            "stream": False,
        }
        if isinstance(self.cfg.get("seed"), int):
            payload["seed"] = self.cfg["seed"]
        if self.cfg.get("reasoning_effort"):
            payload["reasoning_effort"] = self.cfg["reasoning_effort"]

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.cfg['base_url'].rstrip('/')}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise LLMError(_sanitize(exc)) from None

        choice = (body.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("response truncated (finish_reason=length)")
        content = (choice.get("message") or {}).get("content") or ""
        usage = body.get("usage") or {}
        return content, {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

    def _call_ollama(self, facts: dict, system_prompt: str, temperature) -> tuple[str, dict]:
        """Optional local Ollama backend (/api/generate)."""
        self._space_requests()
        options = {
            "temperature": temperature,
            "num_predict": int(self.cfg.get("max_completion_tokens", 400)),
        }
        if isinstance(self.cfg.get("seed"), int):
            options["seed"] = self.cfg["seed"]
        payload = {
            "model": self.cfg["model"],
            "system": system_prompt,
            "prompt": json.dumps(facts, indent=2),
            "stream": False,
            "format": "json",
            "options": options,
        }
        req = urllib.request.Request(
            f"{self.cfg['base_url'].rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise LLMError(_sanitize(exc)) from None

        content = body.get("response") or ""
        usage = {
            "prompt_tokens": body.get("prompt_eval_count"),
            "completion_tokens": body.get("eval_count"),
        }
        return content, usage

    def _transport(self, facts: dict, system_prompt: str, temperature) -> tuple[str, dict]:
        if self.cfg.get("provider") == "ollama":
            return self._call_ollama(facts, system_prompt, temperature)
        return self._call_openai(facts, system_prompt, temperature)

    def _live_attempts(self, facts: dict, system_prompt: str, temperature):
        """Up to MAX_ATTEMPTS with exponential backoff (also on HTTP 429).

        Returns (reason_or_None, usage, retries, last_error).
        """
        usage = None
        last_error = "not attempted"
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(2 ** (attempt - 1))  # exponential backoff: 1s, 2s
            try:
                content, usage = self._transport(facts, system_prompt, temperature)
            except LLMError as exc:
                last_error = str(exc)
                continue
            text = _strip_fences(content)
            try:
                parsed = json.loads(text)
            except Exception:
                last_error = "response is not valid JSON"
                continue
            reason = (parsed.get("reason") or "").strip() if isinstance(parsed, dict) else ""
            if not reason:
                last_error = "response reason is empty"
                continue
            try:
                self.validate(reason, facts)
            except Exception as exc:
                last_error = f"validation failed: {exc}"
                continue
            return reason, usage, attempt, None
        return None, usage, MAX_ATTEMPTS - 1, last_error

    # ------------------------------------------------------------------
    # Usage logging (live calls only)
    # ------------------------------------------------------------------
    def _log_live(self, facts: dict, reason: str | None, usage, retries: int,
                  fallback: bool, error: str | None) -> None:
        self.usage_log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self.cfg["model"],
            "prompt_tokens": usage.get("prompt_tokens") if usage else None,
            "completion_tokens": usage.get("completion_tokens") if usage else None,
            "cache_hit": False,
            "retries": retries,
            "fallback": fallback,
            "route": facts.get("route"),
            "week_of": facts.get("week_of"),
            "verdict": facts.get("VERDICT"),
        }
        if error:
            record["error"] = error
        with open(self.usage_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Resolution: cache -> live (only if enabled) -> template
    # ------------------------------------------------------------------
    def resolve(self, facts: dict, system_prompt: str, temperature=None) -> dict:
        temp = self.cfg["temperature"] if temperature is None else temperature
        key = cache_key(facts, system_prompt, self.cfg["model"], temp, self.cfg["seed"])

        # 1. Cache backend (default; never touches the network).
        if self.use_cache:
            cached = self._cache_get(key, facts)
            if cached is not None:
                return {"reason": cached, "source": "cache", "fallback": False, "retries": 0}

        # 2. Live backend — only when explicitly enabled.
        if self.live:
            reason, usage, retries, error = self._live_attempts(facts, system_prompt, temp)
            if reason is not None:
                # Only validated responses are cached.
                if self.use_cache:
                    self._cache_put(key, reason)
                self._log_live(facts, reason, usage, retries, fallback=False, error=None)
                return {"reason": reason, "source": "live", "fallback": False, "retries": retries}
            self._log_live(facts, None, usage, retries, fallback=True, error=error)

        # 3. Deterministic template (never cached).
        reason = self.template(facts)
        return {"reason": reason, "source": "template", "fallback": True, "retries": 0}
