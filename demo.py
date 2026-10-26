"""Terminal demo: objective -> investigation -> diagnosis -> patch -> verification -> report.

    python demo.py                      # mock model, app.py authorized for one patch
    python demo.py --scenario bad-patch # mock proposes a wrong fix; shows rollback
    python demo.py --read-only          # diagnose only, no patch tool offered
    python demo.py --live               # Nebius Token Factory (needs NEBIUS_API_KEY)
    python demo.py --reset              # restore app.py to the committed baseline
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import investigation_tools
from investigation_loop import investigate_objective
from mock_model import MOCK_LABEL, SCENARIOS, ScriptedMockModelClient


DEFAULT_OBJECTIVE = "Investigate why the /api/users endpoint returns HTTP 500 and fix it."
PATCH_PATH = "app.py"
REPORT_PATH = Path("reports") / "last_run.json"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=investigation_tools.PROJECT_ROOT, capture_output=True, text=True, check=False
    )


def _heading(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 66 - len(title)))


def _pytest_summary(run: dict[str, Any]) -> str:
    if run["timed_out"]:
        return "TIMED OUT"
    lines = [line.strip() for line in run["stdout"].splitlines() if line.strip()]
    return f"exit code {run['exit_code']} | {lines[-1] if lines else 'no output'}"


def _describe(entry: dict[str, Any]) -> str:
    arguments = entry["arguments"]
    label = entry["tool"] + (f"({arguments['relative_path']})" if "relative_path" in arguments else "()")
    if entry["error"]:
        return f"{label:<44} REJECTED: {entry['error']['message']}"
    result = entry["result"]
    if entry["tool"] == "list_files":
        outcome = f"{len(result)} files"
    elif entry["tool"] == "read_file":
        outcome = f"{len(result.splitlines())} lines"
    elif entry["tool"] == "run_tests":
        outcome = _pytest_summary(result)
    else:
        outcome = "patch written, post-patch pytest run"
    return f"{label:<44} -> {outcome}"


def _patch_diff(report: dict[str, Any], entry: dict[str, Any]) -> str:
    path = entry["arguments"]["relative_path"]
    source = next(
        (
            item["result"]
            for item in report["tool_evidence"]
            if item["tool"] == "read_file" and item["arguments"].get("relative_path") == path and not item["error"]
        ),
        None,
    )
    if source is None:
        return f"- {entry['arguments']['expected_text']}\n+ {entry['arguments']['replacement_text']}"
    patched = source.replace(entry["arguments"]["expected_text"], entry["arguments"]["replacement_text"], 1)
    return "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True), patched.splitlines(keepends=True), f"a/{path}", f"b/{path}"
        )
    )


def print_report(report: dict[str, Any], mode_label: str, patch_paths: set[str]) -> None:
    _heading("Objective")
    print(report["objective"])
    print(f"Model:               {mode_label}")
    print(f"Patch authorization: {', '.join(sorted(patch_paths)) or 'none (read-only investigation)'}")

    _heading("Investigation activity (model-selected tool calls)")
    for number, entry in enumerate(report["tool_evidence"], start=1):
        print(f"  E{number:<3}{_describe(entry)}")

    runs = report["test_command"]["runs"]
    _heading("Evidence")
    print(f"Files inspected:     {', '.join(report['files_inspected']) or 'none'}")
    if runs:
        print(f"Tests before patch:  {_pytest_summary(runs[0])}")
    for line in report["observed_failures"] if len(runs) <= 1 else _failure_lines_of(runs[0]):
        print(f"  {line}")

    _heading("Diagnosis (model hypothesis - not a verified fact)")
    print(report["likely_root_cause"].get("hypothesis") or report["likely_root_cause"].get("raw_response") or "none")
    print(f"Next action: {report['recommended_next_action']}")

    patch_entries = [entry for entry in report["tool_evidence"] if entry["tool"] == "apply_text_replacement"]
    for entry in patch_entries:
        _heading("Patch")
        if entry["error"]:
            print(f"Rejected before writing: {entry['error']['message']}")
            continue
        print(_patch_diff(report, entry))
        result = entry["result"]
        print(f"sha256 {result['patch']['original_sha256'][:12]} -> {result['patch']['updated_sha256'][:12]}")
        _heading("Verification (fresh pytest run after the patch)")
        print(f"Tests after patch:   {_pytest_summary(result['verification'])}")
        print(f"Rolled back:         {result['rolled_back']}")
        if result["rollback_error"]:
            print(f"ROLLBACK ERROR:      {result['rollback_error']}")

    _heading("Result")
    status = report["verification_status"].upper().replace("_", " ")
    print(f"Status:        {status}")
    print(f"Stop reason:   {report['stop_reason']}")
    print(f"Changed files: {', '.join(report['changed_files']) or 'none'}")
    if report["model_error"]:
        print(f"Model error:   {report['model_error']['type']}: {report['model_error']['message']}")
    if report["stop_reason"] == "model_configuration_error":
        print("Hint:          set NEBIUS_API_KEY in .env (see .env.example), or run without --live for mock mode.")


def _failure_lines_of(run: dict[str, Any]) -> list[str]:
    return [line.strip() for line in run["stdout"].splitlines() if line.strip().startswith(("FAILED ", "ERROR "))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("objective", nargs="?", default=DEFAULT_OBJECTIVE)
    parser.add_argument("--live", action="store_true", help="use Nebius Token Factory instead of the mock model")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="fix", help="mock model behaviour")
    parser.add_argument("--read-only", action="store_true", help="do not authorize any patch")
    parser.add_argument("--reset", action="store_true", help=f"restore {PATCH_PATH} from git and exit")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    if args.reset:
        result = _git("checkout", "--", PATCH_PATH)
        print(f"Restored {PATCH_PATH} to the committed baseline." if result.returncode == 0 else result.stderr)
        return result.returncode

    if _git("diff", "--quiet", "--", PATCH_PATH).returncode != 0:
        print(f"WARNING: {PATCH_PATH} differs from the committed baseline. Run `python demo.py --reset` first.")

    patch_paths = set() if args.read_only else {PATCH_PATH}
    if args.live:
        model_client = None  # investigate_objective builds NebiusModelClient from the environment
        mode_label = "LIVE - Nebius Token Factory (model from NEBIUS_MODEL or default)"
    else:
        model_client = ScriptedMockModelClient(args.scenario)
        mode_label = f"{MOCK_LABEL}, scenario={args.scenario}"

    print(f"Running investigation ({'live' if args.live else 'mock'} model); pytest runs may take a moment...")
    report = investigate_objective(args.objective, model_client, allowed_patch_paths=patch_paths)
    print_report(report, mode_label, patch_paths)

    report_file = investigation_tools.PROJECT_ROOT / REPORT_PATH
    report_file.parent.mkdir(exist_ok=True)
    report_file.write_text(json.dumps({"mode": mode_label, **report}, indent=2, default=str), encoding="utf-8")
    print(f"\nFull evidence report: {REPORT_PATH.as_posix()}")
    return 0 if report["verification_status"] == "verified" or args.read_only else 1


if __name__ == "__main__":
    sys.exit(main())
