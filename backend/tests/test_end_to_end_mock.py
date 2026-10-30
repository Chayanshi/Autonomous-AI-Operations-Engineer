"""End-to-end runs with the scripted mock model and the real tools, pytest and patcher.

Each test works on a temporary copy of the baseline app so the real repository is untouched.
"""

import shutil
from pathlib import Path

import pytest

import investigation_loop
import investigation_tools
from mock_model import ScriptedMockModelClient


OBJECTIVE = "Investigate why the /api/users endpoint returns HTTP 500 and fix it."
TARGET_TEST = investigation_tools.target_root("users_api") / "tests" / "test_app.py"
# Pinned copy of the baseline app, so these tests stay valid after the demo patches the real app.py.
BASELINE_APP = '''from fastapi import FastAPI, HTTPException

app = FastAPI()


@app.get("/api/users")
def get_users():
    """Return users. The error is intentional for the investigation baseline."""
    raise HTTPException(status_code=500, detail="Intentional baseline failure")
'''


@pytest.fixture
def baseline_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text(BASELINE_APP, encoding="utf-8")
    shutil.copy(TARGET_TEST, tmp_path / "tests" / "test_app.py")
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _tools_used(report: dict) -> list[str]:
    return [entry["tool"] for entry in report["tool_evidence"]]


def test_mock_fix_is_applied_and_verified_by_real_tests(baseline_copy: Path) -> None:
    original = (baseline_copy / "app.py").read_text(encoding="utf-8")
    assert "status_code=500" in original, "baseline bug must be present before the run"

    report = investigation_loop.investigate_objective(
        OBJECTIVE, ScriptedMockModelClient("fix"), allowed_patch_paths={"app.py"}
    )

    assert _tools_used(report) == ["list_files", "read_file", "read_file", "run_tests", "apply_text_replacement"]
    before, after = report["test_command"]["runs"]
    assert before["exit_code"] == 1 and "500 == 200" in before["stdout"]
    assert after["exit_code"] == 0 and not after["timed_out"]
    assert report["verification_status"] == "verified"
    assert report["changed_files"] == ["app.py"]
    assert report["patch_results"][0]["rolled_back"] is False
    assert 'return {"users": []}' in (baseline_copy / "app.py").read_text(encoding="utf-8")
    assert "app.py line" in report["likely_root_cause"]["hypothesis"]


def test_mock_bad_patch_fails_verification_and_is_rolled_back(baseline_copy: Path) -> None:
    original = (baseline_copy / "app.py").read_bytes()

    report = investigation_loop.investigate_objective(
        OBJECTIVE, ScriptedMockModelClient("bad-patch"), allowed_patch_paths={"app.py"}
    )

    patch = report["patch_results"][0]
    assert patch["verified"] is False
    assert patch["rolled_back"] is True
    assert patch["verification"]["exit_code"] == 1
    assert report["verification_status"] == "not_verified"
    assert report["changed_files"] == []
    assert (baseline_copy / "app.py").read_bytes() == original


def test_mock_without_authorization_diagnoses_but_never_writes(baseline_copy: Path) -> None:
    original = (baseline_copy / "app.py").read_bytes()

    report = investigation_loop.investigate_objective(OBJECTIVE, ScriptedMockModelClient("fix"))

    assert "apply_text_replacement" not in _tools_used(report)
    assert report["test_command"]["status"] == "failed"
    assert report["verification_status"] == "not_verified"
    assert report["likely_root_cause"]["hypothesis"]
    assert (baseline_copy / "app.py").read_bytes() == original


def test_propose_mode_writes_nothing_until_the_approved_patch_is_applied(baseline_copy: Path) -> None:
    original = (baseline_copy / "app.py").read_bytes()
    events: list[dict] = []

    report = investigation_loop.investigate_objective(
        OBJECTIVE,
        ScriptedMockModelClient("fix"),
        allowed_patch_paths={"app.py"},
        patch_mode="propose",
        on_event=events.append,
    )

    assert (baseline_copy / "app.py").read_bytes() == original
    assert report["verification_status"] == "awaiting_approval"
    assert report["patch_results"] == []
    proposal = report["patch_proposal"]
    assert proposal["relative_path"] == "app.py" and 'return {"users": []}' in proposal["replacement_text"]
    assert [event["entry"]["tool"] for event in events if event["type"] == "tool_result"] == _tools_used(report)
    assert events[-1]["type"] == "model_turn"

    result = investigation_loop.apply_approved_patch(proposal, {"app.py"})

    assert result["verified"] is True and result["rolled_back"] is False
    assert result["verification"]["exit_code"] == 0
    assert 'return {"users": []}' in (baseline_copy / "app.py").read_text(encoding="utf-8")


def test_approved_bad_patch_is_rolled_back(baseline_copy: Path) -> None:
    original = (baseline_copy / "app.py").read_bytes()
    report = investigation_loop.investigate_objective(
        OBJECTIVE, ScriptedMockModelClient("bad-patch"), allowed_patch_paths={"app.py"}, patch_mode="propose"
    )

    result = investigation_loop.apply_approved_patch(report["patch_proposal"], {"app.py"})

    assert result["verified"] is False and result["rolled_back"] is True
    assert (baseline_copy / "app.py").read_bytes() == original


def test_stale_or_unauthorized_proposals_are_refused(baseline_copy: Path) -> None:
    report = investigation_loop.investigate_objective(
        OBJECTIVE, ScriptedMockModelClient("fix"), allowed_patch_paths={"app.py"}, patch_mode="propose"
    )
    proposal = report["patch_proposal"]

    with pytest.raises(ValueError, match="not explicitly authorized"):
        investigation_loop.apply_approved_patch(proposal, {"other.py"})

    (baseline_copy / "app.py").write_text(BASELINE_APP + "\n# edited after review\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after the patch was proposed"):
        investigation_loop.apply_approved_patch(proposal, {"app.py"})


def test_a_failing_event_observer_does_not_change_the_run(baseline_copy: Path) -> None:
    def broken(_: dict) -> None:
        raise RuntimeError("stream closed")

    report = investigation_loop.investigate_objective(
        OBJECTIVE, ScriptedMockModelClient("fix"), allowed_patch_paths={"app.py"}, patch_mode="propose", on_event=broken
    )

    assert report["verification_status"] == "awaiting_approval"


TARGETS = ["users_api", "config_service", "pagination_api", "profile_api"]


@pytest.fixture
def target_copy(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = investigation_tools.target_root(request.param)
    copy = tmp_path / request.param
    shutil.copytree(source, copy, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", copy)
    return copy


@pytest.mark.parametrize("target_copy", TARGETS, indirect=True)
def test_every_target_is_diagnosed_and_its_approved_fix_verified(target_copy: Path) -> None:
    report = investigation_loop.investigate_objective(
        OBJECTIVE, ScriptedMockModelClient("fix"), allowed_patch_paths={"app.py"}, patch_mode="propose"
    )
    assert report["test_command"]["runs"][0]["exit_code"] == 1, f"{target_copy.name} must be broken at baseline; use Reset target"
    assert report["verification_status"] == "awaiting_approval"
    assert report["likely_root_cause"]["hypothesis"].startswith("app.py line")

    result = investigation_loop.apply_approved_patch(report["patch_proposal"], {"app.py"})

    assert result["verified"] is True, result["verification"]["stdout"]


@pytest.mark.parametrize("target_copy", TARGETS, indirect=True)
def test_every_targets_wrong_fix_fails_and_is_rolled_back(target_copy: Path) -> None:
    original = (target_copy / "app.py").read_bytes()
    report = investigation_loop.investigate_objective(
        OBJECTIVE, ScriptedMockModelClient("bad-patch"), allowed_patch_paths={"app.py"}, patch_mode="propose"
    )

    result = investigation_loop.apply_approved_patch(report["patch_proposal"], {"app.py"})

    assert result["verified"] is False and result["rolled_back"] is True
    assert (target_copy / "app.py").read_bytes() == original


def test_unknown_bug_is_not_guessed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text("def total(values):\n    return sum(values) + 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text(
        "from app import total\n\ndef test_total():\n    assert total([1, 2]) == 3\n", encoding="utf-8"
    )
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)

    report = investigation_loop.investigate_objective(
        "Fix the failing total test.", ScriptedMockModelClient("fix"), allowed_patch_paths={"app.py"}, patch_mode="propose"
    )

    assert report["patch_proposal"] is None
    assert report["verification_status"] == "not_verified"
    assert "not identified" in report["likely_root_cause"]["hypothesis"]
