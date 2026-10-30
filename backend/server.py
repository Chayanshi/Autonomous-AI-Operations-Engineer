"""HTTP API for the React UI. It only delegates to the existing bounded agent code.

The browser never chooses file paths, commands or patch text: the only editable path is the
fixed PATCH_PATH, patches are always proposed first, and only the exact reviewed proposal can
be applied on approval.

    uvicorn server:app --port 8001
"""

from __future__ import annotations

import difflib
import json
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import investigation_loop
import investigation_tools
from ai_settings import AiSettings
from mock_model import MOCK_LABEL, ScriptedMockModelClient
from target_catalog import describe_target


PATCH_PATH = "app.py"
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
HEARTBEAT_SECONDS = 15.0
# Plain-language causes by error type; the provider's own message is never shown (it may echo request details).
MODEL_ERROR_HINTS = {
    "AuthenticationError": "the API key was rejected",
    "PermissionDeniedError": "the provider refused access. For Gemini this usually means the Google project has no free tier and needs billing enabled in AI Studio",
    "NotFoundError": "the model name is not available for this key",
    "RateLimitError": "rate limit or quota exceeded",
    "APIConnectionError": "the provider could not be reached",
    "APITimeoutError": "the provider took too long to answer",
    "BadRequestError": "the provider rejected the request, often because of the model name",
}
TERMINAL = "completed"


class SettingsUpdate(BaseModel):
    provider: Literal["mock", "nebius", "gemini"] | None = None
    model: str | None = Field(default=None, max_length=100)
    api_key: str | None = Field(default=None, max_length=400)
    clear_key: bool = False
    max_output_tokens: int | None = None
    run_token_budget: int | None = None


class RunRequest(BaseModel):
    target: str = Field(default=investigation_tools.DEFAULT_TARGET, max_length=64)
    objective: str = Field(default=describe_target(investigation_tools.DEFAULT_TARGET)["objective"], min_length=1, max_length=500)
    scenario: Literal["fix", "bad-patch"] = "fix"
    allow_patch: bool = True


@dataclass
class Run:
    id: str
    request: RunRequest
    model: dict[str, Any]
    state: str = "running"  # running -> awaiting_approval -> verifying -> completed
    events: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    condition: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, event: dict[str, Any]) -> None:
        with self.condition:
            self.events.append({"seq": len(self.events) + 1, "time": time.time(), **event})
            self.condition.notify_all()

    def set_state(self, state: str, **event: Any) -> None:
        with self.condition:
            self.state = state
        self.emit({"type": "state", "state": state, **event})

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "request": self.request.model_dump(),
            "model": self.model,
            "outcome": self.outcome,
            "report": self.report,
        }


_runs: dict[str, Run] = {}
_registry_lock = threading.Lock()
_settings = AiSettings()


def _active_run() -> Run | None:
    return next((run for run in _runs.values() if run.state != TERMINAL), None)


def _get_run(run_id: str) -> Run:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _target_root(name: str) -> Path:
    return investigation_tools.target_root(name)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _baseline_clean(name: str) -> bool | None:
    """True when the target's app.py matches git; None when git does not track it yet."""
    root = _target_root(name)
    if _git(root, "ls-files", "--error-unmatch", PATCH_PATH).returncode != 0:
        return None
    return {0: True, 1: False}.get(_git(root, "diff", "--quiet", "--", PATCH_PATH).returncode)


def _diff(proposal: dict[str, Any]) -> str:
    path = proposal["relative_path"]
    source = investigation_tools.read_file(path)
    patched = source.replace(proposal["expected_text"], proposal["replacement_text"], 1)
    return "".join(
        difflib.unified_diff(source.splitlines(keepends=True), patched.splitlines(keepends=True), f"a/{path}", f"b/{path}")
    )


def _finish(run: Run, status: str, message: str, patch_result: dict[str, Any] | None = None) -> None:
    run.outcome = {"status": status, "message": message, "patch_result": patch_result}
    run.emit({"type": "outcome", **run.outcome})
    run.set_state(TERMINAL)


def _investigate(run: Run, model_client: Any, token_budget: int | None) -> None:
    request = run.request
    try:
        report = investigation_loop.investigate_objective(
            request.objective,
            model_client,
            allowed_patch_paths={PATCH_PATH} if request.allow_patch else set(),
            patch_mode="propose",
            on_event=run.emit,
            token_budget=token_budget,
        )
    except Exception as error:
        _finish(run, "error", f"Investigation failed: {type(error).__name__}")
        return

    with _settings.lock:
        _settings.session_usage.add(report["token_usage"])
        _settings.last_run_usage = {**report["token_usage"], "token_budget": token_budget, "run_id": run.id}
    run.report = report
    run.emit({"type": "report", "report": report})
    proposal = report["patch_proposal"]
    if report["verification_status"] == "awaiting_approval" and proposal is not None:
        try:
            diff = _diff(proposal)
        except Exception as error:
            _finish(run, "not_verified", f"Could not render the proposed patch: {type(error).__name__}")
            return
        run.set_state("awaiting_approval", proposal=proposal, diff=diff)
        return
    error_type = (report["model_error"] or {}).get("type", "")
    reason = {
        "model_configuration_error": "Live model is not configured; nothing was changed.",
        "model_error": f"The model request failed ({error_type}): {MODEL_ERROR_HINTS.get(error_type, 'check the API key, model name and quota')}. Nothing was changed.",
        "token_budget": "The run reached its token budget before finishing; nothing was changed.",
    }.get(report["stop_reason"], "Investigation finished without a patch to review; nothing was changed.")
    _finish(run, "not_verified", reason)


def _verify(run: Run) -> None:
    proposal = run.report["patch_proposal"]
    try:
        result = investigation_loop.apply_approved_patch(proposal, {PATCH_PATH})
    except ValueError as error:
        _finish(run, "not_verified", f"Patch refused: {error}")
        return
    except Exception as error:
        _finish(run, "error", f"Patch application failed: {type(error).__name__}")
        return
    if result["verified"]:
        _finish(run, "verified", "Approved patch applied; the full pytest suite passed afterwards.", result)
    elif result["rolled_back"]:
        _finish(run, "not_verified", "Post-patch tests failed; the original file was restored.", result)
    else:
        _finish(run, "error", result["rollback_error"] or "Verification failed and rollback did not complete.", result)


app = FastAPI(title="OpsPilot API")


@app.get("/api/status")
def status() -> dict[str, Any]:
    active = _active_run()
    return {
        "mock_label": MOCK_LABEL,
        "patch_path": PATCH_PATH,
        "default_target": investigation_tools.TARGET_NAME,
        "targets": [_target_status(name) for name in investigation_tools.available_targets()],
        "active_run_id": active.id if active else None,
        "limits": investigation_loop.LIMITS,
    }


def _target_status(name: str) -> dict[str, Any]:
    return {"name": name, **describe_target(name), "baseline_clean": _baseline_clean(name)}


@app.post("/api/runs", status_code=201)
def start_run(request: RunRequest) -> dict[str, Any]:
    if not request.objective.strip():
        raise HTTPException(status_code=422, detail="An objective is required")
    if request.target not in investigation_tools.available_targets():
        raise HTTPException(status_code=422, detail="Unknown target")
    with _registry_lock:
        if _active_run() is not None:
            raise HTTPException(status_code=409, detail="Another run is in progress")
        # Safe as a process-wide switch: only one run may be active, and reset is refused meanwhile.
        with _settings.lock:
            provider = _settings.provider
            if not _settings.ready(provider):
                raise HTTPException(status_code=400, detail=f"{provider} needs an API key; add one in AI settings")
            model_info = {"provider": provider, "model": _settings.model_for(provider)}
            token_budget = None if provider == "mock" else _settings.run_token_budget
            try:
                model_client = ScriptedMockModelClient(request.scenario) if provider == "mock" else _settings.build_client()
            except Exception as error:
                raise HTTPException(status_code=400, detail=f"Could not configure {provider}: {type(error).__name__}")
        investigation_tools.PROJECT_ROOT = _target_root(request.target)
        run = Run(id=uuid.uuid4().hex[:12], request=request, model=model_info)
        _runs[run.id] = run
    run.emit({"type": "run_started", "request": request.model_dump(), "model": model_info, "token_budget": token_budget})
    threading.Thread(target=_investigate, args=(run, model_client, token_budget), daemon=True).start()
    return run.summary()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return _get_run(run_id).summary()


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: str) -> dict[str, Any]:
    run = _get_run(run_id)
    with run.condition:
        if run.state != "awaiting_approval":
            raise HTTPException(status_code=409, detail="This run is not awaiting approval")
        run.state = "verifying"
    run.emit({"type": "state", "state": "verifying"})
    threading.Thread(target=_verify, args=(run,), daemon=True).start()
    return run.summary()


@app.post("/api/runs/{run_id}/reject")
def reject(run_id: str) -> dict[str, Any]:
    run = _get_run(run_id)
    with run.condition:
        if run.state != "awaiting_approval":
            raise HTTPException(status_code=409, detail="This run is not awaiting approval")
        run.state = "rejecting"
    _finish(run, "rejected", "The proposed patch was rejected by the reviewer; nothing was changed.")
    return run.summary()


@app.get("/api/runs/{run_id}/events")
def events(run_id: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    run = _get_run(run_id)
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    def stream() -> Iterator[str]:
        nonlocal cursor
        while True:
            with run.condition:
                run.condition.wait_for(lambda: len(run.events) > cursor or run.state == TERMINAL, HEARTBEAT_SECONDS)
                pending = run.events[cursor:]
                finished = run.state == TERMINAL
            if not pending and not finished:
                yield ": heartbeat\n\n"
            for event in pending:
                cursor = event["seq"]
                yield f"id: {event['seq']}\ndata: {json.dumps(event, default=str)}\n\n"
            if finished and cursor >= len(run.events):
                yield "event: end\ndata: {}\n\n"
                return

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    if _active_run() is not None:
        raise HTTPException(status_code=409, detail="Cannot reset while a run is in progress")
    restored = []
    for name in investigation_tools.available_targets():
        if _baseline_clean(name) is False:
            if _git(_target_root(name), "checkout", "--", PATCH_PATH).returncode != 0:
                raise HTTPException(status_code=500, detail=f"git checkout failed for {name}")
            restored.append(name)
    return {"restored": restored, "targets": [_target_status(name) for name in investigation_tools.available_targets()]}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    with _settings.lock:
        return _settings.public_view()


@app.put("/api/settings")
def update_settings(update: SettingsUpdate) -> dict[str, Any]:
    if _active_run() is not None:
        raise HTTPException(status_code=409, detail="Settings cannot change while a run is in progress")
    with _settings.lock:
        try:
            _settings.update(update.model_dump(exclude_none=True))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        return _settings.public_view()


@app.post("/api/settings/test")
def test_connection() -> dict[str, Any]:
    """One tiny request to the selected provider; reports only success or the error type."""
    with _settings.lock:
        provider = _settings.provider
        if provider == "mock":
            return {"ok": True, "provider": provider, "message": "Mock provider needs no connection."}
        if not _settings.ready(provider):
            return {"ok": False, "provider": provider, "message": "No API key configured."}
        client = _settings.build_client()
    try:
        usage = client.ping()
    except Exception as error:  # provider errors can echo request details; report only the type
        return {"ok": False, "provider": provider, "model": client.model, "message": type(error).__name__}
    if usage is not None:
        with _settings.lock:
            _settings.session_usage.add(
                {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "model_calls": 1, "usage_reported": True},
                run=False,
            )
    return {"ok": True, "provider": provider, "model": client.model, "message": "Connected; the model answered."}


if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
