"""Deterministic stand-in for the Nebius model, used only when live access is unavailable.

MOCK MODE: these turns are produced by a fixed rule-based policy, not by an LLM.
The policy still speaks the same tool-calling protocol as the live client and
derives every argument from the real tool results it receives, so the tools,
the patch, the verification run and the report are all real.
"""

from __future__ import annotations

import json
import re
from typing import Any

from model_client import ModelToolCall, ModelTurn


SCENARIOS = {"fix", "bad-patch"}
MOCK_LABEL = "MOCK MODEL (scripted rule-based policy, not live LLM output)"

_RAISE_500 = re.compile(r"^(?P<indent>[ \t]*)raise HTTPException\(status_code=500[^\r\n]*(?=\r?$)", re.MULTILINE)


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

        if "read_file" not in names:
            files = _result_for(results, "list_files") or []
            source = "app.py" if "app.py" in files else None
            test = next((path for path in files if path.startswith("tests/") and "app" in path), None)
            reads = [("read_file", {"relative_path": path}) for path in (source, test) if path]
            if not reads:
                return self._final("No application source or test file was found.", "Locate the endpoint manually.")
            return self._calls(*reads)

        if "run_tests" not in names:
            return self._calls(("run_tests", {}))

        source = _read_result(results, "app.py")
        match = _RAISE_500.search(source or "")
        tests = _result_for(results, "run_tests") or {}
        failure = _first_failure(tests)

        if patch_offered and match and "apply_text_replacement" not in names:
            body = '{"users": []}' if self.scenario == "fix" else '{"users": None}'
            return self._calls(
                (
                    "apply_text_replacement",
                    {
                        "relative_path": "app.py",
                        "expected_text": match.group(0),
                        "replacement_text": f"{match.group('indent')}return {body}",
                    },
                )
            )

        if not match:
            return self._final(
                "No unconditional HTTP 500 was found in app.py; the cause is not identified by this policy.",
                "Inspect the remaining evidence manually.",
            )

        line_number = source[: match.start()].count("\n") + 1
        cause = (
            f"app.py line {line_number} unconditionally executes `{match.group(0).strip()}` in get_users, "
            f"so GET /api/users can never succeed. Supporting test evidence: {failure or 'pytest exited non-zero'}."
        )
        patch = _result_for(results, "apply_text_replacement")
        if patch is None:
            next_action = 'Authorize app.py and replace the raise with `return {"users": []}`, then rerun pytest.'
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


def _read_result(results: list[tuple[str, dict[str, Any], Any]], path: str) -> str | None:
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
