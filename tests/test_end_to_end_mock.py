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
REPOSITORY = Path(__file__).resolve().parent.parent
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
    shutil.copy(REPOSITORY / "tests" / "test_app.py", tmp_path / "tests" / "test_app.py")
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
