"""Deterministic stand-in for the Nebius model, used only when live access is unavailable.

MOCK MODE: these turns are produced by a fixed rule-based policy, not by an LLM.
The policy still speaks the same tool-calling protocol as the live client and
derives every argument from the real tool results it receives, so the tools,
the patch, the verification run and the report are all real.

It knows a small library of bug patterns. A rule fires only when both the source
and the captured test output support it; otherwise the policy says it cannot
diagnose the issue instead of guessing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from model_client import ModelToolCall, ModelTurn


SCENARIOS = {"fix", "bad-patch"}
MOCK_LABEL = "MOCK MODEL (scripted rule-based policy, not live LLM output)"


@dataclass(frozen=True)
class Finding:
    rule: str
    start: int
    expected_text: str
    fix_text: str
    wrong_fix_text: str
    cause: str
    fix_summary: str


def _unconditional_500(source: str, test_source: str, output: str) -> Finding | None:
    match = re.search(r"^(?P<indent>[ \t]*)raise HTTPException\(status_code=500[^\r\n]*(?=\r?$)", source, re.MULTILINE)
    healthy = re.search(r"response\.json\(\) == (\{[^\r\n]*\})", test_source)
    if not match or not healthy or "500" not in output:
        return None
    indent = match.group("indent")
    return Finding(
        rule="unconditional_http_500",
        start=match.start(),
        expected_text=match.group(0),
        fix_text=f"{indent}return {healthy.group(1)}",
        wrong_fix_text=f"{indent}return {{}}",
        cause=f"the handler unconditionally executes `{match.group(0).strip()}`, so the endpoint can never succeed",
        fix_summary=f"return the healthy response `{healthy.group(1)}` that the test expects",
    )


def _missing_environment_variable(source: str, test_source: str, output: str) -> Finding | None:
    error = re.search(r"KeyError: '([A-Za-z_][A-Za-z0-9_]*)'", output)
    if not error:
        return None
    name = error.group(1)
    access = re.search(rf"os\.environ\[([\"']){re.escape(name)}\1\]", source)
    default = re.search(rf"^DEFAULT_{re.escape(name)}\s*=", source, re.MULTILINE)
    if not access or not default:
        return None
    return Finding(
        rule="missing_environment_variable",
        start=access.start(),
        expected_text=access.group(0),
        fix_text=f'os.environ.get("{name}", DEFAULT_{name})',
        wrong_fix_text=f'os.environ.get("{name}")',
        cause=(
            f"configuration is read with `{access.group(0)}` at import time, so the service crashes with "
            f"KeyError whenever {name} is not set, even though DEFAULT_{name} is defined but never used"
        ),
        fix_summary=f"fall back to DEFAULT_{name} when {name} is not configured",
    )


def _off_by_one_slice(source: str, test_source: str, output: str) -> Finding | None:
    match = re.search(r"\[\s*(\w+)\s*:\s*\1\s*\+\s*(\w+)\s*-\s*1\s*\]", source)
    lists = re.search(r"assert \[([^\]]*)\] == \[([^\]]*)\]", output)
    if not match or not lists:
        return None
    actual, expected = (len([item for item in group.split(",") if item.strip()]) for group in lists.groups())
    if actual != expected - 1:
        return None
    start, size = match.groups()
    return Finding(
        rule="off_by_one_slice",
        start=match.start(),
        expected_text=match.group(0),
        fix_text=f"[{start} : {start} + {size}]",
        wrong_fix_text=f"[{start} : {start} + {size} + 1]",
        cause=f"the slice `{match.group(0)}` stops one element early (Python slice ends are already exclusive), so every page is one item short",
        fix_summary=f"remove the extra `- 1` so a page holds `{size}` items",
    )


def _method_call_on_none(source: str, test_source: str, output: str) -> Finding | None:
    error = re.search(r"AttributeError: 'NoneType' object has no attribute '(\w+)'", output)
    if not error:
        return None
    method = error.group(1)
    call = re.search(rf"(\w+\[[\"']\w+[\"']\])\.{re.escape(method)}\(\)", source)
    if not call:
        return None
    value = call.group(1)
    return Finding(
        rule="method_call_on_none",
        start=call.start(),
        expected_text=call.group(0),
        fix_text=f"{value}.{method}() if {value} is not None else None",
        wrong_fix_text=f'({value} or "").{method}()',
        cause=f"`{call.group(0)}` assumes the value is always a string, but some records store None, which raises AttributeError (HTTP 500)",
        fix_summary=f"call `.{method}()` only when the value is present and keep None otherwise",
    )


RULES: list[Callable[[str, str, str], Finding | None]] = [
    _unconditional_500,
    _missing_environment_variable,
    _off_by_one_slice,
    _method_call_on_none,
]


def diagnose(source: str, test_source: str, output: str) -> Finding | None:
    for rule in RULES:
        finding = rule(source, test_source, output)
        if finding is not None and source.count(finding.expected_text) == 1:
            return finding
    return None


class ScriptedMockModelClient:
    """Plays one fixed investigation strategy against real tool results."""

    model = "mock/scripted-policy"

    def __init__(self, scenario: str = "fix") -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown mock scenario: {scenario}")
        self.scenario = scenario
        self._call_counter = 0

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelTurn:
        results = _tool_results(messages)
        names = [name for name, _, _ in results]
        patch_offered = any(tool["function"]["name"] == "apply_text_replacement" for tool in tools)

        if "list_files" not in names:
            return self._calls(("list_files", {}))

        files = _result_for(results, "list_files") or []
        test_path = next((path for path in files if path.startswith("tests/") and "app" in path), None)
        if "read_file" not in names:
            reads = [("read_file", {"relative_path": path}) for path in ("app.py" if "app.py" in files else None, test_path) if path]
            if not reads:
                return self._final("No application source or test file was found.", "Locate the endpoint manually.")
            return self._calls(*reads)

        if "run_tests" not in names:
            return self._calls(("run_tests", {}))

        source = _read_result(results, "app.py") or ""
        test_source = _read_result(results, test_path) or ""
        tests = _result_for(results, "run_tests") or {}
        output = f"{tests.get('stdout', '')}\n{tests.get('stderr', '')}"
        finding = diagnose(source, test_source, output)

        if finding is None:
            return self._final(
                "None of the mock policy's known bug patterns matched both the source and the test output; "
                "the cause is not identified.",
                "Use live mode, or inspect the captured evidence manually.",
            )

        if patch_offered and "apply_text_replacement" not in names:
            replacement = finding.fix_text if self.scenario == "fix" else finding.wrong_fix_text
            return self._calls(
                (
                    "apply_text_replacement",
                    {"relative_path": "app.py", "expected_text": finding.expected_text, "replacement_text": replacement},
                )
            )

        line_number = source[: finding.start].count("\n") + 1
        cause = (
            f"app.py line {line_number}: {finding.cause}. "
            f"Supporting test evidence: {_first_failure(tests) or 'pytest exited non-zero'}."
        )
        patch = _result_for(results, "apply_text_replacement")
        if patch is None:
            next_action = f"Authorize app.py and {finding.fix_summary}, then rerun pytest."
        elif patch.get("status") == "proposed_for_human_review":
            next_action = f"A minimal patch was proposed for human review ({finding.fix_summary}); approve it to apply and verify with pytest."
        elif patch.get("verified"):
            next_action = "Post-patch pytest passed per the tool result; review and commit the change."
        else:
            next_action = "The patch failed post-patch verification and was rolled back; revise the replacement."
        return self._final(cause, next_action)

    def _calls(self, *calls: tuple[str, dict[str, Any]]) -> ModelTurn:
        tool_calls = []
        for name, arguments in calls:
            self._call_counter += 1
            tool_calls.append(ModelToolCall(id=f"mock-{self._call_counter}", name=name, arguments=json.dumps(arguments)))
        return ModelTurn(content=None, tool_calls=tuple(tool_calls))

    @staticmethod
    def _final(cause: str, next_action: str) -> ModelTurn:
        return ModelTurn(
            content=json.dumps({"likely_root_cause": cause, "recommended_next_action": next_action}),
            tool_calls=(),
        )


def _tool_results(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], Any]]:
    """Pair each tool result message with the call (name, arguments) that produced it."""
    requested: dict[str, tuple[str, dict[str, Any]]] = {}
    paired = []
    for message in messages:
        for call in message.get("tool_calls", []) if message.get("role") == "assistant" else []:
            requested[call["id"]] = (call["function"]["name"], json.loads(call["function"]["arguments"] or "{}"))
        if message.get("role") == "tool" and message.get("tool_call_id") in requested:
            name, arguments = requested[message["tool_call_id"]]
            paired.append((name, arguments, json.loads(message["content"])))
    return paired


def _result_for(results: list[tuple[str, dict[str, Any], Any]], name: str) -> Any:
    for tool_name, _, result in reversed(results):
        if tool_name == name and not (isinstance(result, dict) and "error" in result):
            return result
    return None


def _read_result(results: list[tuple[str, dict[str, Any], Any]], path: str | None) -> str | None:
    for tool_name, arguments, result in results:
        if tool_name == "read_file" and arguments.get("relative_path") == path and isinstance(result, str):
            return result
    return None


def _first_failure(test_result: dict[str, Any]) -> str | None:
    output = f"{test_result.get('stdout', '')}\n{test_result.get('stderr', '')}"
    lines = [line.strip() for line in output.splitlines()]
    failed = next((line.removeprefix("FAILED ").split(" - ")[0] for line in lines if line.startswith("FAILED ")), None)
    assertion = next((line.removeprefix("E").strip() for line in lines if line.startswith("E ")), None)
    if failed and assertion:
        return f"{failed} failed with `{assertion}`"
    return failed or assertion
