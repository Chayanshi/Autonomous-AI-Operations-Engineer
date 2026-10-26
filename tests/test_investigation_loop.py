import json
from pathlib import Path

import pytest

import investigation_loop
import investigation_tools
from model_client import ModelToolCall, ModelTurn
from investigation_tools import TestRunResult as ToolRunResult


class FakeModelClient:
    def __init__(self, turns: list[ModelTurn | Exception]) -> None:
        self.turns = turns
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelTurn:
        self.calls.append((messages.copy(), tools))
        next_turn = self.turns.pop(0)
        if isinstance(next_turn, Exception):
            raise next_turn
        return next_turn


def call(call_id: str, name: str, arguments: str) -> ModelToolCall:
    return ModelToolCall(id=call_id, name=name, arguments=arguments)


def test_model_selects_tools_from_objective_and_previous_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = '@app.get("/api/users")\ndef get_users():\n    raise HTTPException(status_code=500)\n'
    test = "def test_users():\n    assert response.status_code == 200\n"
    test_result = {
        "stdout": "FAILED tests/test_app.py::test_users - assert 500 == 200\n",
        "stderr": "",
        "exit_code": 1,
        "timed_out": False,
    }

    def read_file(path: str) -> str:
        return source if path == "app.py" else test

    monkeypatch.setattr(investigation_tools, "list_files", lambda: ["app.py", "tests/test_app.py"])
    monkeypatch.setattr(investigation_tools, "read_file", read_file)
    monkeypatch.setattr(investigation_tools, "run_tests", lambda: test_result)
    model = FakeModelClient(
        [
            ModelTurn(content=None, tool_calls=(call("1", "list_files", "{}"),)),
            ModelTurn(
                content=None,
                tool_calls=(
                    call("2", "read_file", '{"relative_path":"app.py"}'),
                    call("3", "read_file", '{"relative_path":"tests/test_app.py"}'),
                    call("4", "run_tests", "{}"),
                ),
            ),
            ModelTurn(
                content=json.dumps(
                    {
                        "likely_root_cause": "The handler appears to raise HTTP 500.",
                        "recommended_next_action": "Review app.py before a separate fix milestone.",
                    }
                ),
                tool_calls=(),
            ),
        ]
    )

    report = investigation_loop.investigate_objective("Investigate /api/users HTTP 500", model)

    assert len(model.calls) == 3
    assert model.calls[0][1] == investigation_loop.TOOL_SCHEMAS
    assert '"app.py"' in model.calls[1][0][-1]["content"]
    assert report["objective"] == "Investigate /api/users HTTP 500"
    assert report["files_inspected"] == ["app.py", "tests/test_app.py"]
    assert report["test_command"]["argv"][-3:] == ["-m", "pytest", "-q"]
    assert report["test_command"]["status"] == "failed"
    assert report["test_command"]["result"] == test_result
    assert report["observed_failures"] == [
        "FAILED tests/test_app.py::test_users - assert 500 == 200"
    ]
    assert report["verified_facts"] == [
        "The bounded pytest command exited with code 1.",
        "FAILED tests/test_app.py::test_users - assert 500 == 200",
    ]
    assert report["likely_root_cause"] == {
        "hypothesis": "The handler appears to raise HTTP 500.",
        "source": "model_generated",
        "verified": False,
    }
    assert report["recommended_next_action"] == "Review app.py before a separate fix milestone."
    assert report["verification_status"] == "not_verified"
    assert [item["tool"] for item in report["tool_evidence"]] == [
        "list_files", "read_file", "read_file", "run_tests"
    ]
    assert report["tool_evidence"][0]["result"] == ["app.py", "tests/test_app.py"]
    assert report["tool_evidence"][-1]["result"] == test_result


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("delete_file", "{}", "not available"),
        ("list_files", '{"path":"."}', "accepts no arguments"),
        ("read_file", '{"relative_path":"../secret.txt"}', "stay inside"),
        ("read_file", '{"relative_path":".env"}', "Credential and secret"),
        ("run_tests", '{"command":"python anything"}', "accepts no arguments"),
        ("read_file", "not json", "not valid JSON"),
    ],
)
def test_untrusted_tool_requests_are_rejected_before_execution(
    monkeypatch: pytest.MonkeyPatch, name: str, arguments: str, message: str
) -> None:
    def unexpected_read(path: str) -> str:
        pytest.fail(f"read_file should not have executed for {path}")

    monkeypatch.setattr(investigation_tools, "read_file", unexpected_read)
    model = FakeModelClient(
        [
            ModelTurn(content=None, tool_calls=(call("bad", name, arguments),)),
            ModelTurn(content='{"likely_root_cause":"","recommended_next_action":"Review the rejected call."}', tool_calls=()),
        ]
    )

    report = investigation_loop.investigate_objective("Investigate this issue", model)

    error = report["tool_evidence"][0]["error"]
    assert error["type"] == "ValueError"
    assert message in error["message"]
    assert report["verification_status"] == "not_verified"


def test_model_tool_error_limit_stops_calls() -> None:
    invalid_turn = ModelTurn(content=None, tool_calls=(call("bad", "delete_file", "{}"),))
    model = FakeModelClient([invalid_turn, invalid_turn, invalid_turn, invalid_turn])

    report = investigation_loop.investigate_objective("Inspect files", model)

    assert len(model.calls) == investigation_loop.MAX_TOOL_ERRORS
    assert report["stop_reason"] == "tool_error_limit"
    assert all(entry["error"] for entry in report["tool_evidence"])
    assert report["verification_status"] == "not_verified"


def test_model_iteration_limit_stops_repeated_tool_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(investigation_tools, "list_files", lambda: [])
    repeated_turn = ModelTurn(content=None, tool_calls=(call("list", "list_files", "{}"),))
    model = FakeModelClient([repeated_turn] * investigation_loop.MAX_MODEL_ITERATIONS)

    report = investigation_loop.investigate_objective("Inspect files", model)

    assert len(model.calls) == investigation_loop.MAX_MODEL_ITERATIONS
    assert report["stop_reason"] == "iteration_limit"
    assert report["verification_status"] == "not_verified"


def test_model_timeout_is_reported_without_provider_details() -> None:
    model = FakeModelClient([TimeoutError("secret-api-key-should-not-appear")])

    report = investigation_loop.investigate_objective("Investigate failure", model)

    assert report["stop_reason"] == "model_error"
    assert report["model_error"]["type"] == "TimeoutError"
    assert "secret-api-key" not in json.dumps(report)
    assert report["test_command"]["status"] == "not_run"
    assert report["verification_status"] == "not_verified"


def test_tool_content_redacts_credentials_before_model_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "neb-secret-value-123456"
    monkeypatch.setenv("NEBIUS_API_KEY", secret)
    monkeypatch.setattr(investigation_tools, "read_file", lambda path: f"api_key={secret}")
    model = FakeModelClient(
        [
            ModelTurn(content=None, tool_calls=(call("read", "read_file", '{"relative_path":"config.py"}'),)),
            ModelTurn(content='{"likely_root_cause":"Unknown","recommended_next_action":"Continue inspection."}', tool_calls=()),
        ]
    )

    report = investigation_loop.investigate_objective("Inspect config.py", model)

    assert secret not in json.dumps(report)
    assert "[REDACTED]" in report["tool_evidence"][0]["result"]
    assert "[REDACTED]" in model.calls[1][0][-1]["content"]


def test_investigate_objective_requires_objective() -> None:
    with pytest.raises(ValueError, match="objective is required"):
        investigation_loop.investigate_objective(" ", FakeModelClient([]))


def test_patch_requires_explicit_path_and_is_verified_after_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)
    target = tmp_path / "app.py"
    target.write_text("return 500", encoding="utf-8")
    passing_tests = ToolRunResult("26 passed", "", 0, False)
    monkeypatch.setattr(investigation_tools, "run_tests", lambda: passing_tests)
    patch_args = json.dumps(
        {
            "relative_path": "app.py",
            "expected_text": "return 500",
            "replacement_text": "return 200",
        }
    )
    model = FakeModelClient(
        [
            ModelTurn(content=None, tool_calls=(call("patch", "apply_text_replacement", patch_args),)),
            ModelTurn(content='{"likely_root_cause":"The handler returned 500.","recommended_next_action":"Done."}', tool_calls=()),
        ]
    )

    report = investigation_loop.investigate_objective(
        "Correct the endpoint response", model, allowed_patch_paths={"app.py"}
    )

    assert target.read_text(encoding="utf-8") == "return 200"
    assert model.calls[0][1][-1] == investigation_loop.PATCH_TOOL_SCHEMA
    assert report["changed_files"] == ["app.py"]
    assert report["patch_results"][0]["verified"] is True
    assert report["patch_results"][0]["verification"]["exit_code"] == 0
    assert report["verification_status"] == "verified"


def test_failed_post_patch_tests_restore_original_and_do_not_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)
    target = tmp_path / "app.py"
    target.write_text("return 500", encoding="utf-8")
    failing_tests = ToolRunResult("FAILED test_app.py", "", 1, False)
    monkeypatch.setattr(investigation_tools, "run_tests", lambda: failing_tests)
    patch_args = json.dumps(
        {
            "relative_path": "app.py",
            "expected_text": "return 500",
            "replacement_text": "return 200",
        }
    )
    model = FakeModelClient(
        [
            ModelTurn(content=None, tool_calls=(call("patch", "apply_text_replacement", patch_args),)),
            ModelTurn(content='{"likely_root_cause":"Unknown","recommended_next_action":"Review failure."}', tool_calls=()),
        ]
    )

    report = investigation_loop.investigate_objective(
        "Correct the endpoint response", model, allowed_patch_paths={"app.py"}
    )

    assert target.read_text(encoding="utf-8") == "return 500"
    assert report["patch_results"][0]["rolled_back"] is True
    assert report["changed_files"] == []
    assert report["test_command"]["status"] == "failed"
    assert report["verification_status"] == "not_verified"


def test_patch_tool_is_rejected_without_explicit_authorization() -> None:
    patch_call = call(
        "patch",
        "apply_text_replacement",
        '{"relative_path":"app.py","expected_text":"old","replacement_text":"new"}',
    )
    model = FakeModelClient(
        [
            ModelTurn(content=None, tool_calls=(patch_call,)),
            ModelTurn(content='{"likely_root_cause":"Unknown","recommended_next_action":"Review."}', tool_calls=()),
        ]
    )

    report = investigation_loop.investigate_objective("Review the endpoint", model)

    assert all(tool["function"]["name"] != "apply_text_replacement" for tool in model.calls[0][1])
    assert "explicitly authorized" in report["tool_evidence"][0]["error"]["message"]
    assert report["verification_status"] == "not_verified"


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"likely_root_cause": "raise in get_users", "recommended_next_action": "patch"}\n```',
        'Here is my assessment:\n{"likely_root_cause": "raise in get_users", "recommended_next_action": "patch"}',
    ],
)
def test_fenced_or_prefixed_final_json_is_parsed(content: str) -> None:
    assessment, next_action = investigation_loop._model_assessment(content)

    assert assessment["hypothesis"] == "raise in get_users"
    assert assessment["verified"] is False
    assert next_action == "patch"


def test_unstructured_final_response_is_kept_raw() -> None:
    assessment, _ = investigation_loop._model_assessment("I think it is broken.")

    assert assessment["hypothesis"] is None
    assert assessment["raw_response"] == "I think it is broken."
