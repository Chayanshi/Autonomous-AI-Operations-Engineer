"""OpenAI-compatible chat-completion client for the supported providers, separate from local tools.

Nebius Token Factory and Google Gemini both expose an OpenAI-compatible chat API with tool calling,
so one adapter serves both; a provider only changes the base URL, default model and key variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
REQUEST_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    base_url: str
    default_model: str
    key_env: str
    base_url_env: str
    model_env: str


PROVIDERS: dict[str, ProviderSpec] = {
    "nebius": ProviderSpec(
        "nebius", "Nebius Token Factory", DEFAULT_BASE_URL, DEFAULT_MODEL, "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "NEBIUS_MODEL"
    ),
    "gemini": ProviderSpec(
        "gemini",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.8-flash",
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        "GEMINI_MODEL",
    ),
}


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: str
    # Opaque provider fields (e.g. Gemini 3 thought signatures) that must be echoed back unchanged.
    provider_fields: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ModelTurn:
    content: str | None
    tool_calls: tuple[ModelToolCall, ...]
    usage: TokenUsage | None = None  # None when the provider did not report usage
    provider_fields: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


class ModelConfigurationError(ValueError):
    """Raised when the required provider configuration is missing."""


def environment_key(provider: str) -> str | None:
    load_dotenv()
    return os.environ.get(PROVIDERS[provider].key_env) or None


def configured_model(provider: str) -> str:
    spec = PROVIDERS[provider]
    return os.environ.get(spec.model_env, spec.default_model)


class ChatModelClient:
    """Small adapter for an OpenAI-compatible chat API with tool calling."""

    def __init__(self, sdk_client: Any, model: str, provider: str = "nebius", max_output_tokens: int | None = None) -> None:
        self._sdk_client = sdk_client
        self.model = model
        self.provider = provider
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_environment(cls) -> "ChatModelClient":
        return cls.for_provider("nebius")

    @classmethod
    def for_provider(
        cls,
        provider: str,
        api_key: str | None = None,
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> "ChatModelClient":
        if provider not in PROVIDERS:
            raise ModelConfigurationError(f"Unknown provider: {provider}")
        spec = PROVIDERS[provider]
        key = api_key or environment_key(provider)
        if not key:
            raise ModelConfigurationError(f"{spec.key_env} is required")

        base_url = os.environ.get(spec.base_url_env, spec.base_url).rstrip("/")
        sdk_client = OpenAI(
            api_key=key,
            base_url=base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        return cls(sdk_client=sdk_client, model=model or configured_model(provider), provider=provider, max_output_tokens=max_output_tokens)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        options: dict[str, Any] = {"max_tokens": self.max_output_tokens} if self.max_output_tokens else {}
        response = self._sdk_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            **options,
        )
        if not response.choices:
            raise RuntimeError("The provider returned no completion choices")

        message = response.choices[0].message
        calls = tuple(
            ModelToolCall(
                id=call.id,
                name=call.function.name,
                arguments=call.function.arguments or "{}",
                provider_fields=_extra_fields(call, {"id", "type", "function"}),
            )
            for call in (message.tool_calls or [])
        )
        return ModelTurn(
            content=message.content,
            tool_calls=calls,
            usage=_usage(response),
            provider_fields=_extra_fields(message, _STANDARD_MESSAGE_FIELDS),
        )


    def ping(self) -> TokenUsage | None:
        """Smallest possible request, to check the key, endpoint and model name before a run."""
        response = self._sdk_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": "Reply with the single word OK."}],
            max_tokens=32,
        )
        if not response.choices:
            raise RuntimeError("The provider returned no completion choices")
        return _usage(response)


_STANDARD_MESSAGE_FIELDS = {"role", "content", "tool_calls", "refusal", "audio", "function_call", "annotations"}


def _extra_fields(item: Any, standard: set[str]) -> dict[str, Any]:
    """Non-standard fields the provider attached to a message or tool call, kept for the next request."""
    dump = getattr(item, "model_dump", None)
    if not callable(dump):
        return {}
    try:
        data = dump(exclude_none=True)
    except Exception:
        return {}
    return {key: value for key, value in data.items() if key not in standard} if isinstance(data, dict) else {}


def _usage(response: Any) -> TokenUsage | None:
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None)
    output_tokens = getattr(usage, "completion_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    return TokenUsage(input_tokens, output_tokens)


# Backwards-compatible name used by the loop and existing tests.
NebiusModelClient = ChatModelClient
