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


def test_gemini_provider_uses_its_openai_compatible_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    openai_factory = Mock(return_value=Mock())
    monkeypatch.setattr(model_client, "OpenAI", openai_factory)

    client = model_client.ChatModelClient.for_provider("gemini", api_key="user-key", max_output_tokens=512)

    openai_factory.assert_called_once_with(
        api_key="user-key",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        timeout=model_client.REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
    assert client.model == "gemini-3.8-flash" and client.provider == "gemini"


def test_output_cap_is_sent_and_usage_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    message = SimpleNamespace(content="done", tool_calls=None)
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=80)
    )
    sdk_client = Mock()
    sdk_client.chat.completions.create.return_value = completion
    client = model_client.ChatModelClient(sdk_client, "gemini-test", provider="gemini", max_output_tokens=256)

    turn = client.complete([{"role": "user", "content": "hi"}], [])

    assert sdk_client.chat.completions.create.call_args.kwargs["max_tokens"] == 256
    assert turn.usage == model_client.TokenUsage(1200, 80)


def test_missing_usage_is_reported_as_unknown_not_zero() -> None:
    sdk_client = Mock()
    sdk_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="x", tool_calls=None))], usage=None
    )

    turn = model_client.ChatModelClient(sdk_client, "m").complete([], [])

    assert turn.usage is None


def test_gemini_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(model_client, "load_dotenv", lambda: None)

    with pytest.raises(model_client.ModelConfigurationError, match="GEMINI_API_KEY is required"):
        model_client.ChatModelClient.for_provider("gemini")


def test_gemini_thought_signatures_are_echoed_back_on_the_next_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    import investigation_loop
    import investigation_tools
    from openai.types.chat import ChatCompletion

    signed = ChatCompletion.model_validate(
        {
            "id": "r1",
            "object": "chat.completion",
            "created": 0,
            "model": "gemini-test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "list_files", "arguments": "{}"},
                                "extra_content": {"google": {"thought_signature": "SIG-123"}},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
    )
    final = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"likely_root_cause": "x", "recommended_next_action": "y"}', tool_calls=None))],
        usage=None,
    )
    sdk_client = Mock()
    sdk_client.chat.completions.create.side_effect = [signed, final]
    monkeypatch.setattr(investigation_tools, "list_files", lambda: ["app.py"])

    investigation_loop.investigate_objective("Inspect", model_client.ChatModelClient(sdk_client, "gemini-test", provider="gemini"))

    second_request = sdk_client.chat.completions.create.call_args_list[1].kwargs["messages"]
    echoed = next(message for message in second_request if message.get("tool_calls"))["tool_calls"][0]
    assert echoed["extra_content"] == {"google": {"thought_signature": "SIG-123"}}
    assert echoed["id"] == "c1" and echoed["function"]["name"] == "list_files"
