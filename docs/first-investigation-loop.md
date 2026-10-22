# First Investigation and Verification Loop

## Goal

Given an engineering objective, gather repository evidence, explain the likely cause, make a targeted change when authorized, and report success only after independent verification.

## Loop

1. **Scope the objective.** Record the user request and identify the relevant application and test command. For the first demo, the objective is to make `GET /api/users` return HTTP 200 with `{"users": []}`.
2. **Collect evidence.** Inspect repository status, relevant source and test files, and project instructions. Run the existing test command and capture its exit code and output.
3. **Diagnose.** Use the observed failure and source code to state a root cause. Tie each claim to a file, test result, or command output. If evidence is insufficient, stop and report what is missing.
4. **Propose a small patch.** Produce a diff limited to files relevant to the diagnosis. Do not edit tests simply to hide the failure.
5. **Apply and verify.** Apply the patch, rerun the reproducing test, then run the project's full test suite when available. Report success only if the required checks pass after the change.
6. **Report.** Return the root cause, supporting evidence, changed files, exact checks and results, and a final status of `verified`, `not verified`, or `blocked`.

## First Demo Tools and Boundaries

- `list_files()` returns paths relative to the repository root and omits Git metadata, virtual environments, caches, and other generated directories.
- `read_file(relative_path)` reads UTF-8 files only within the repository root, rejects absolute and traversing paths and outside-resolving symlinks, and enforces a one MiB size limit.
- `run_tests()` accepts no command arguments. It runs only the current Python interpreter's `-m pytest -q` command, captures stdout, stderr, and exit code, and stops after 120 seconds.
- Keep command output, exit status, and the files inspected as evidence attached to the run.
- These tools do not write files. A future patch-writing capability must be separately bounded to the repository root.
- Do not offer arbitrary shell execution, deletion, network access, or automatic commits in this first loop.
- Keep the initial patch small and reviewable. The user objective authorizes fixing the reported issue; stop before a write if the objective does not authorize changes or the proposed patch exceeds its scope.
- After any change, rerun verification from a fresh command. A generated or applied patch alone is never a successful result.

## Model-Driven Investigation Milestone

`investigate_objective(objective)` sends the objective and the three existing read-only tool schemas to `NebiusModelClient`. The model chooses `list_files`, `read_file`, and `run_tests` calls based on the objective and results returned in prior turns. Every call is validated against a fixed name and argument schema before dispatch. The loop is limited to eight model turns, twenty tool calls, and three tool errors; the model request has a 45-second timeout and SDK retries are disabled.

`model_client.py` adapts Nebius Token Factory's OpenAI-compatible chat-completions API. It reads `NEBIUS_API_KEY` from the environment; the default API base URL is `https://api.tokenfactory.nebius.com/v1`, and the default model is `nvidia/nemotron-3-super-120b-a12b`. `NEBIUS_BASE_URL` and `NEBIUS_MODEL` can override these defaults. Provider errors are reported without provider detail, and known credentials are redacted from tool content before it is retained or sent back to the model.

The report stores tool observations separately from the model-generated hypothesis. It remains read-only by default. A caller may explicitly authorize exactly one repository-relative Python path by passing `allowed_patch_paths={"app.py"}`. Only then does the model receive `apply_text_replacement`, which permits one patch attempt: one exact current text match and one replacement. The patcher rejects paths outside that allowlist, unsafe paths, symlinks, oversized inputs, stale or non-unique matches, and non-Python files. It writes one file atomically, immediately runs the existing fixed pytest command, and restores the original bytes if the tests fail or time out. A report says `verified` only when an authorized patch was applied, the post-patch pytest run passed, and the model turn completed; otherwise it remains `not_verified`. The report includes patch hashes, verification output, changed paths, and rollback status. The existing `/api/users` baseline remains unchanged until a caller explicitly authorizes that path in a separate run.

## First Demo Acceptance

With the intentional baseline bug present, the loop must collect a failing test result showing HTTP 500 versus expected HTTP 200. After a targeted fix, it must collect a passing test result before reporting `verified`. The final report must distinguish observed evidence from the agent's explanation.
