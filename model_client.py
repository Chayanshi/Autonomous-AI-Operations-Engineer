"""Nebius Token Factory chat-completion client, separate from local tools."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"
REQUEST_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelTurn:
    content: str | None
    tool_calls: tuple[ModelToolCall, ...]


class ModelConfigurationError(ValueError):
    """Raised when the required Token Factory configuration is missing."""


class NebiusModelClient:
    """Small adapter for the Token Factory OpenAI-compatible chat API."""

    def __init__(self, sdk_client: Any, model: str) -> None:
        self._sdk_client = sdk_client
        self.model = model

    @classmethod
    def from_environment(cls) -> "NebiusModelClient":
        load_dotenv()
        api_key = os.environ.get("NEBIUS_API_KEY")
        if not api_key:
            raise ModelConfigurationError("NEBIUS_API_KEY is required")

        base_url = os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        model = os.environ.get("NEBIUS_MODEL", DEFAULT_MODEL)
        sdk_client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        return cls(sdk_client=sdk_client, model=model)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        response = self._sdk_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        if not response.choices:
            raise RuntimeError("Token Factory returned no completion choices")

        message = response.choices[0].message
        calls = tuple(
            ModelToolCall(
                id=call.id,
                name=call.function.name,
                arguments=call.function.arguments or "{}",
            )
            for call in (message.tool_calls or [])
        )
        return ModelTurn(content=message.content, tool_calls=calls)
