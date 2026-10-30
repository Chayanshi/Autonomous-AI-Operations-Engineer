"""UI API tests: real agent code on a temporary baseline copy, with a fast fake pytest run."""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ai_settings
import investigation_tools
import server
from mock_model import ScriptedMockModelClient
from model_client import ModelTurn, TokenUsage
from investigation_tools import TestRunResult as ToolRunResult
from tests.test_end_to_end_mock import BASELINE_APP, TARGET_TEST


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text(BASELINE_APP, encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text(TARGET_TEST.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)

    def fake_run_tests() -> ToolRunResult:
        source = (tmp_path / "app.py").read_text(encoding="utf-8")
        if 'return {"users": []}' in source:
            return ToolRunResult("1 passed in 0.01s\n", "", 0, False)
        return ToolRunResult(
            "E       assert 500 == 200\nFAILED tests/test_app.py::test_users - assert 500 == 200\n1 failed\n", "", 1, False
        )

    monkeypatch.setattr(investigation_tools, "run_tests", fake_run_tests)
    monkeypatch.setattr(server, "_runs", {})
    monkeypatch.setattr(server, "_baseline_clean", lambda name: True)
    monkeypatch.setattr(server, "_target_root", lambda name: tmp_path)
    monkeypatch.setattr(ai_settings, "environment_key", lambda provider: None)  # ignore any real .env keys
    monkeypatch.setattr(server, "_settings", ai_settings.AiSettings())
    return TestClient(server.app)


def _wait_for(client: TestClient, run_id: str, state: str) -> dict:
    deadline = time.time() + 20
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["state"] == state:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run never reached {state}")


def test_run_waits_for_approval_then_verifies(client: TestClient) -> None:
    run = client.post("/api/runs", json={}).json()
    _wait_for(client, run["id"], "awaiting_approval")
    app_file = investigation_tools.PROJECT_ROOT / "app.py"
    assert app_file.read_text(encoding="utf-8") == BASELINE_APP, "nothing may be written before approval"

    assert client.post(f"/api/runs/{run['id']}/approve").status_code == 200
    done = _wait_for(client, run["id"], "completed")

    assert done["outcome"]["status"] == "verified"
    assert done["outcome"]["patch_result"]["verification"]["exit_code"] == 0
    assert 'return {"users": []}' in app_file.read_text(encoding="utf-8")


def test_bad_patch_is_rolled_back_after_approval(client: TestClient) -> None:
    run = client.post("/api/runs", json={"scenario": "bad-patch"}).json()
    _wait_for(client, run["id"], "awaiting_approval")
    client.post(f"/api/runs/{run['id']}/approve")
    done = _wait_for(client, run["id"], "completed")

    assert done["outcome"]["status"] == "not_verified"
    assert done["outcome"]["patch_result"]["rolled_back"] is True
    assert (investigation_tools.PROJECT_ROOT / "app.py").read_text(encoding="utf-8") == BASELINE_APP


def test_reject_changes_nothing_and_frees_the_repository(client: TestClient) -> None:
    run = client.post("/api/runs", json={}).json()
    _wait_for(client, run["id"], "awaiting_approval")
    assert client.post("/api/runs", json={}).status_code == 409, "only one run may hold the repository"

    done = client.post(f"/api/runs/{run['id']}/reject").json()

    assert done["state"] == "completed" and done["outcome"]["status"] == "rejected"
    assert client.post(f"/api/runs/{run['id']}/approve").status_code == 409
    assert (investigation_tools.PROJECT_ROOT / "app.py").read_text(encoding="utf-8") == BASELINE_APP
    assert client.post("/api/runs", json={}).status_code == 201


def test_read_only_run_never_offers_a_patch(client: TestClient) -> None:
    run = client.post("/api/runs", json={"allow_patch": False}).json()
    done = _wait_for(client, run["id"], "completed")

    assert done["outcome"]["status"] == "not_verified"
    assert done["report"]["patch_proposal"] is None


def test_request_validation_and_live_mode_gate(client: TestClient) -> None:
    assert client.put("/api/settings", json={"provider": "gemini"}).status_code == 200
    assert client.post("/api/runs", json={}).status_code == 400, "a keyless live provider must not start"
    client.put("/api/settings", json={"provider": "mock"})
    assert client.post("/api/runs", json={"objective": ""}).status_code == 422
    assert client.post("/api/runs", json={"target": "../backend"}).status_code == 422
    assert client.post("/api/runs", json={"target": "not_a_target"}).status_code == 422
    assert client.post("/api/runs", json={"objective": "x" * 501}).status_code == 422
    assert client.post("/api/runs", json={"patch_path": "../evil.py"}).json()["request"].get("patch_path") is None
    status = client.get("/api/status").json()
    assert status["patch_path"] == "app.py"
    names = [target["name"] for target in status["targets"]]
    assert {"users_api", "config_service", "pagination_api", "profile_api"} <= set(names)
    assert all(target["symptom"] and target["objective"] for target in status["targets"])
    assert "NEBIUS_API_KEY" not in json.dumps(status).replace("NEBIUS_API_KEY in", "")


def test_event_stream_replays_progress_in_order(client: TestClient) -> None:
    run = client.post("/api/runs", json={"allow_patch": False}).json()
    _wait_for(client, run["id"], "completed")

    with client.stream("GET", f"/api/runs/{run['id']}/events") as response:
        body = "".join(response.iter_text())

    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {\"")]
    types = [event["type"] for event in events]
    assert types[0] == "run_started" and types[-1] == "state"
    assert "tool_result" in types and "report" in types and "outcome" in types
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert "event: end" in body


SECRET = "AIza-test-secret-key-0001"


def test_api_key_is_accepted_but_never_returned(client: TestClient) -> None:
    response = client.put("/api/settings", json={"provider": "gemini", "api_key": SECRET, "model": "gemini-test"})

    assert response.status_code == 200
    assert SECRET not in response.text and SECRET not in client.get("/api/settings").text
    gemini = next(item for item in response.json()["providers"] if item["name"] == "gemini")
    assert gemini["key_source"] == "user" and gemini["ready"] is True and gemini["model"] == "gemini-test"

    cleared = client.put("/api/settings", json={"provider": "gemini", "clear_key": True}).json()
    assert next(item for item in cleared["providers"] if item["name"] == "gemini")["ready"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "openai"},
        {"provider": "gemini", "model": "bad model; rm -rf"},
        {"provider": "gemini", "api_key": "short"},
        {"provider": "gemini", "api_key": "has spaces in it"},
        {"max_output_tokens": 10},
        {"run_token_budget": 10_000_000},
    ],
)
def test_invalid_settings_are_rejected(client: TestClient, body: dict) -> None:
    assert client.put("/api/settings", json=body).status_code == 422


class UsageReportingMock(ScriptedMockModelClient):
    """Stands in for a live provider: real mock decisions, plus provider-style token usage."""

    model = "gemini-test"

    def complete(self, messages, tools):
        turn = super().complete(messages, tools)
        return ModelTurn(turn.content, turn.tool_calls, usage=TokenUsage(1_000, 100))


def test_live_provider_run_tracks_tokens_and_settings_lock_during_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put(
        "/api/settings", json={"provider": "gemini", "api_key": SECRET, "model": "gemini-test", "run_token_budget": 50_000}
    )
    monkeypatch.setattr(ai_settings.AiSettings, "build_client", lambda self, provider=None: UsageReportingMock("fix"))

    run = client.post("/api/runs", json={}).json()
    assert run["model"] == {"provider": "gemini", "model": "gemini-test"}
    awaiting = _wait_for(client, run["id"], "awaiting_approval")
    assert client.put("/api/settings", json={"provider": "mock"}).status_code == 409

    usage = awaiting["report"]["token_usage"]
    # list files, read files, run tests, propose patch, final answer
    assert usage == {"input_tokens": 5_000, "output_tokens": 500, "model_calls": 5, "usage_reported": True}
    settings = client.get("/api/settings").json()
    assert settings["session_usage"]["input_tokens"] == 5_000 and settings["session_usage"]["runs"] == 1
    assert settings["last_run_usage"]["token_budget"] == 50_000
    client.post(f"/api/runs/{run['id']}/reject")


def test_connection_check_reports_only_success_or_error_type(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        model = "gemini-test"

        def __init__(self, error: Exception | None) -> None:
            self.error = error

        def ping(self):
            if self.error:
                raise self.error
            return TokenUsage(7, 1)

    client.put("/api/settings", json={"provider": "gemini", "api_key": SECRET})
    monkeypatch.setattr(ai_settings.AiSettings, "build_client", lambda self, provider=None: FakeClient(None))
    assert client.post("/api/settings/test").json()["ok"] is True
    assert client.get("/api/settings").json()["session_usage"]["input_tokens"] == 7

    leaky = PermissionError(f"401 invalid key {SECRET}")
    monkeypatch.setattr(ai_settings.AiSettings, "build_client", lambda self, provider=None: FakeClient(leaky))
    failed = client.post("/api/settings/test")
    assert failed.json() == {"ok": False, "provider": "gemini", "model": "gemini-test", "message": "PermissionError"}
    assert SECRET not in failed.text
