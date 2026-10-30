"""Upstream providers. Token Factory (Nebius) is the default and the only provider the submission uses.

`openrouter` is a DEV-ONLY fallback for building and testing the live gateway / Hermes sandbox path while Token Factory credit is
exhausted. It serves the same Nemotron models on the free tier. Everything upstream of the provider switch is identical: the
pseudonymizer, the canary and fail-closed behaviour run on the final bytes, so only tokenized synthetic data can leave. The only
differences are the base URL, which environment variable holds the key, the model ids, and a few request adjustments for reasoning models.

The key is read from the environment only (never written, logged, ledgered or put in a run record).
Any run through a non-default provider is labelled as such in the ledger, every receipt, and the run record, and is kept out of the static bundle.
"""
from __future__ import annotations
import os

DEFAULT = "tokenfactory"
TOKENFACTORY_BASE = "https://api.tokenfactory.nebius.com/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

PROVIDERS = {
    "tokenfactory": dict(base=TOKENFACTORY_BASE, key_env="NEBIUS_API_KEY", label="Nebius Token Factory", dev=False),
    "openrouter": dict(base=OPENROUTER_BASE, key_env="OPENROUTER_API_KEY", label="OpenRouter", dev=True),
}

# The ids the gateway exposes (and the sandbox/Hermes ask for) -> the ids OpenRouter serves. Verified against GET /api/v1/models.
OPENROUTER_MODELS = {
    "nvidia/Nemotron-3-Ultra-550b-a55b": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/Nemotron-3_5-Lightning": "nvidia/nemotron-3.5-lightning:free",
}
DEV_LABEL = "OpenRouter dev fallback, not a Nebius Token Factory run"
MIN_MAX_TOKENS = 8192  # reasoning models spend completion tokens on thinking first; a small cap leaves an empty answer
RETRY_STATUSES = (429,)


def active_provider() -> str:
    """VEIL_PROVIDER, default tokenfactory. An unknown value is an error, never a silent fallback."""
    p = (os.environ.get("VEIL_PROVIDER") or DEFAULT).strip().lower()
    if p not in PROVIDERS:
        raise ValueError(f"VEIL_PROVIDER must be one of {sorted(PROVIDERS)}, got {p!r}")
    return p


def is_dev(provider: str | None) -> bool:
    return bool(provider) and provider in PROVIDERS and PROVIDERS[provider]["dev"]


def label(provider: str | None) -> str | None:
    return DEV_LABEL if provider == "openrouter" else None


def upstream_model(provider: str, model: str) -> str:
    return OPENROUTER_MODELS.get(model, model) if provider == "openrouter" else model


def key_for(provider: str) -> str | None:
    """OpenRouter: the environment only (the shell that starts the gateway sources ~/.zshrc). No file scraping, no fallback."""
    if provider == "openrouter":
        k = os.environ.get("OPENROUTER_API_KEY")
        return k.strip() if k and k.strip() else None
    return None  # tokenfactory keeps its existing loader in config.load_api_key


def adapt_request(provider: str, body: dict) -> dict:
    """Provider-specific tweaks to the ALREADY REDACTED body, before the canary runs, so the canary still sees the final bytes."""
    if provider != "openrouter":
        return body
    b = dict(body)
    b["model"] = upstream_model(provider, b.get("model"))
    kw = b.get("chat_template_kwargs")
    thinking_off = isinstance(kw, dict) and kw.get("enable_thinking") is False
    if isinstance(kw, dict):  # Nebius/vLLM spelling of the Lightning thinking switch; OpenRouter spells it `reasoning`
        kw = {k: v for k, v in kw.items() if k != "enable_thinking"}
        if kw:
            b["chat_template_kwargs"] = kw
        else:
            b.pop("chat_template_kwargs")
        if thinking_off and "reasoning" not in b:
            b["reasoning"] = {"enabled": False}
    for k in ("max_tokens", "max_completion_tokens"):
        if isinstance(b.get(k), int) and b[k] < MIN_MAX_TOKENS and not thinking_off:
            b[k] = MIN_MAX_TOKENS
    if not thinking_off and not any(isinstance(b.get(k), int) for k in ("max_tokens", "max_completion_tokens")):
        b["max_tokens"] = MIN_MAX_TOKENS
    return b


def upstream_headers(provider: str, key: str | None) -> dict:
    h = {"Authorization": f"Bearer {key or 'test'}", "Content-Type": "application/json"}
    if provider == "openrouter":
        h["X-Title"] = "Veil (dev fallback)"
    return h


def retry_delay(attempt: int, retry_after: str | None, base: float) -> float:
    """429 back-off: honour Retry-After (capped), else exponential from `base` seconds."""
    try:
        if retry_after:
            return min(float(retry_after), 30.0)
    except ValueError:
        pass
    return min(base * (2 ** attempt), 30.0)
