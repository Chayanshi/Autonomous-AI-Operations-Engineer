from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import model_client


def test_model_client_reads_configuration_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key-never-logged")
    monkeypatch.setenv("NEBIUS_BASE_URL", "https://regional.example/v1/")
    monkeypatch.setenv("NEBIUS_MODEL", "nvidia/test-model")
    sdk_client = Mock()
    openai_factory = Mock(return_value=sdk_client)
    monkeypatch.setattr(model_client, "OpenAI", openai_factory)

    client = model_client.NebiusModelClient.from_environment()

    openai_factory.assert_called_once_with(
        api_key="test-key-never-logged",
        base_url="https://regional.example/v1",
        timeout=model_client.REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    assert client.model == "nvidia/test-model"


def test_model_client_uses_documented_chat_tool_call_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name="list_files", arguments="{}"),
            )
        ],
    )
    completion = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    sdk_client = Mock()
    sdk_client.chat.completions.create.return_value = completion
    monkeypatch.setattr(model_client, "OpenAI", Mock(return_value=sdk_client))
    client = model_client.NebiusModelClient.from_environment()
    tools = [{"type": "function", "function": {"name": "list_files"}}]
    messages = [{"role": "user", "content": "Inspect the repository"}]

    turn = client.complete(messages, tools)

    sdk_client.chat.completions.create.assert_called_once_with(
        model=model_client.DEFAULT_MODEL,
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )
    assert turn.content is None
    assert turn.tool_calls == (model_client.ModelToolCall("call-1", "list_files", "{}"),)


def test_model_client_requires_nebius_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    openai_factory = Mock()
    monkeypatch.setattr(model_client, "OpenAI", openai_factory)

    with pytest.raises(model_client.ModelConfigurationError, match="NEBIUS_API_KEY is required"):
        model_client.NebiusModelClient.from_environment()

    openai_factory.assert_not_called()
