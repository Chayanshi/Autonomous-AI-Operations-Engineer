"""Runtime AI provider settings, bring-your-own-key storage and token accounting.

Keys typed into the UI are kept only in this process's memory: never written to disk, never
logged, never returned by the API (only whether a key is present and where it came from), and
registered for redaction so they cannot leak into evidence or model context. Restarting the
backend forgets them. Limits are enforced here and in the loop, not in the browser.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

import investigation_loop
from model_client import PROVIDERS, ChatModelClient, configured_model, environment_key


PROVIDER_CHOICES = ("mock", *PROVIDERS)
MAX_OUTPUT_TOKENS_RANGE = (256, 8_192)
RUN_TOKEN_BUDGET_RANGE = (10_000, 500_000)
_MODEL_NAME = re.compile(r"[A-Za-z0-9._:/-]{1,100}")
_API_KEY = re.compile(r"[^\s]{8,400}")

PROVIDER_NOTES = {
    "mock": "A pre-written script plays the AI. Free, offline and always available; uses no tokens.",
    "nebius": "NVIDIA Nemotron and other open models on Nebius Token Factory, billed to your Nebius account.",
    "gemini": "Google Gemini through its OpenAI-compatible API, billed to (or free tier of) your Google AI Studio key.",
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    runs: int = 0
    usage_reported: bool = True

    def add(self, report_usage: dict[str, Any], run: bool = True) -> None:
        self.input_tokens += report_usage["input_tokens"]
        self.output_tokens += report_usage["output_tokens"]
        self.model_calls += report_usage["model_calls"]
        self.runs += 1 if run else 0
        self.usage_reported = self.usage_reported and report_usage["usage_reported"]


@dataclass
class AiSettings:
    provider: str = "mock"
    max_output_tokens: int = 2_048
    run_token_budget: int = 100_000
    models: dict[str, str] = field(default_factory=dict)
    _keys: dict[str, str] = field(default_factory=dict, repr=False)
    session_usage: Usage = field(default_factory=Usage)
    last_run_usage: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def model_for(self, provider: str) -> str | None:
        if provider == "mock":
            return None
        return self.models.get(provider) or configured_model(provider)

    def key_source(self, provider: str) -> str | None:
        if provider == "mock":
            return None
        if provider in self._keys:
            return "user"
        return "environment" if environment_key(provider) else None

    def ready(self, provider: str) -> bool:
        return provider == "mock" or self.key_source(provider) is not None

    def update(self, changes: dict[str, Any]) -> None:
        """Validate every change first, then apply them all at once."""
        provider = changes.get("provider", self.provider)
        if provider not in PROVIDER_CHOICES:
            raise ValueError("Unknown provider")
        model = changes.get("model")
        if model is not None and (provider == "mock" or not _MODEL_NAME.fullmatch(model)):
            raise ValueError("Model names may use letters, digits and . _ : / - (up to 100 characters)")
        api_key = changes.get("api_key")
        if api_key is not None and (provider == "mock" or not _API_KEY.fullmatch(api_key)):
            raise ValueError("API key must be 8-400 characters without spaces")
        output_tokens = changes.get("max_output_tokens", self.max_output_tokens)
        budget = changes.get("run_token_budget", self.run_token_budget)
        if not MAX_OUTPUT_TOKENS_RANGE[0] <= output_tokens <= MAX_OUTPUT_TOKENS_RANGE[1]:
            raise ValueError("max_output_tokens is out of range")
        if not RUN_TOKEN_BUDGET_RANGE[0] <= budget <= RUN_TOKEN_BUDGET_RANGE[1]:
            raise ValueError("run_token_budget is out of range")

        self.provider = provider
        self.max_output_tokens = output_tokens
        self.run_token_budget = budget
        if model is not None:
            self.models[provider] = model
        if changes.get("clear_key") and provider != "mock":
            self._keys.pop(provider, None)
        if api_key is not None:
            investigation_loop.register_secret(api_key)
            self._keys[provider] = api_key

    def build_client(self, provider: str | None = None) -> ChatModelClient:
        provider = provider or self.provider
        return ChatModelClient.for_provider(
            provider,
            api_key=self._keys.get(provider),
            model=self.model_for(provider),
            max_output_tokens=self.max_output_tokens,
        )

    def public_view(self) -> dict[str, Any]:
        """Everything the UI may see. Keys are reported only as present/absent and their source."""
        return {
            "provider": self.provider,
            "providers": [
                {
                    "name": name,
                    "label": "Mock (offline demo)" if name == "mock" else PROVIDERS[name].label,
                    "note": PROVIDER_NOTES[name],
                    "model": self.model_for(name),
                    "default_model": None if name == "mock" else PROVIDERS[name].default_model,
                    "key_source": self.key_source(name),
                    "key_variable": None if name == "mock" else PROVIDERS[name].key_env,
                    "ready": self.ready(name),
                }
                for name in PROVIDER_CHOICES
            ],
            "max_output_tokens": self.max_output_tokens,
            "run_token_budget": self.run_token_budget,
            "bounds": {"max_output_tokens": MAX_OUTPUT_TOKENS_RANGE, "run_token_budget": RUN_TOKEN_BUDGET_RANGE},
            "session_usage": vars(self.session_usage).copy(),
            "last_run_usage": self.last_run_usage,
        }
