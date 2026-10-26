# Autonomous AI Operations Engineer

An engineering agent that takes an **objective** ("find out why `/api/users` returns 500 and fix it"), investigates a repository with bounded tools, forms an evidence-linked hypothesis, applies a narrowly scoped patch only when explicitly authorized, re-runs the real test suite, and rolls back automatically if verification fails. It never reports `verified` unless the post-patch tests actually passed.

The FastAPI app in `app.py` is only the test subject: its `/api/users` endpoint intentionally returns HTTP 500 so the agent has something to repair.

## Demo

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python demo.py                       # investigate -> diagnose -> patch app.py -> verify  => VERIFIED
python demo.py --reset               # restore app.py to the committed (broken) baseline
python demo.py --scenario bad-patch  # a wrong fix fails verification and is rolled back => NOT VERIFIED
python demo.py --read-only           # diagnosis only; the patch tool is never offered
python demo.py --live                # same workflow driven by Nebius Token Factory
```

The demo prints the objective, every model-selected tool call, the evidence gathered, the diagnosis (labelled as a hypothesis), the patch as a unified diff, the before/after pytest results and the final status. The complete evidence report is written to `reports/last_run.json`. Run `--reset` between runs.

### Mock mode vs live mode

| | Mock mode (default) | Live mode (`--live`) |
|---|---|---|
| Who chooses tool calls | `mock_model.py`: a fixed, rule-based policy | NVIDIA Nemotron 3 Super via Nebius Token Factory |
| Tools, patcher, pytest, rollback, report | Real | Real |
| Status | Demonstrated, covered by end-to-end tests | Integration path implemented and unit-tested with a mocked SDK; **no live call has been demonstrated yet** |

Mock mode is clearly labelled in the demo output and the report. The scripted policy speaks the same tool-calling protocol as the live client and derives every argument (files to read, the exact text to replace) from real tool results, but it is not an LLM and its output must not be presented as model output.

For live mode, copy `.env.example` to `.env` and set `NEBIUS_API_KEY`. `NEBIUS_BASE_URL` (default `https://api.tokenfactory.nebius.com/v1`) and `NEBIUS_MODEL` (default `nvidia/nemotron-3-super-120b-a12b`) are optional. `.env` is git-ignored. Without a key, `--live` stops with `model_configuration_error` and changes nothing.

## How it works

```
objective ─► investigation_loop ─► model (live Nemotron or mock policy)
                 │   ▲                    │ tool calls (validated against a fixed schema)
                 │   └── tool results ◄───┘
                 ├─ investigation_tools: list_files / read_file / run_tests   (read-only)
                 └─ patch_tools: apply_text_replacement → pytest → rollback on failure
                                                       (only if a path is authorized)
           ─► report: evidence, hypothesis, patch hashes, verification, status
```

| File | Responsibility |
|---|---|
| `investigation_loop.py` | Bounded model ↔ tool loop, argument validation, redaction, report |
| `investigation_tools.py` | Repo-confined file listing/reading and the single fixed pytest command |
| `patch_tools.py` | One exact-text replacement in one authorized file; atomic write; hash-checked rollback |
| `model_client.py` | Nebius Token Factory client (OpenAI-compatible chat + tool calling) |
| `mock_model.py` | Deterministic stand-in for the model when live access is unavailable |
| `demo.py` | Terminal demo and report writer |

## Safety boundaries

- The model never gets a shell. It can call only `list_files`, `read_file`, `run_tests` and, when authorized, `apply_text_replacement`; names and arguments are validated before execution.
- File reads stay inside the repository (no absolute paths, `..`, or escaping symlinks; 1 MiB cap). `.env`, keys and credential files are never sent to the model.
- `run_tests` runs only `python -m pytest -q` with a 120 s timeout.
- Patching is off by default. The caller authorizes at most one Python file; one patch attempt per run; the expected text must match exactly once.
- After a patch the full suite runs immediately. Failure or timeout restores the original bytes, and only if the file still matches what the patch wrote.
- `verified` requires an authorized patch, a passing post-patch run, and a completed model turn. Every other outcome is `not_verified`.
- Limits: 8 model turns, 20 tool calls, 3 tool errors, 45 s per model request. Known secrets are redacted from evidence and model context; provider error details are omitted.

## Tests

```powershell
python -m pytest
```

Expected at baseline: **1 failed, all others passed**. The failure is `tests/test_app.py`, the intentional `/api/users` HTTP 500, and it is left in place deliberately; it passes once the agent's fix is applied. `tests/test_end_to_end_mock.py` runs the full workflow (real tools, real pytest subprocess, real patch and rollback) on a temporary copy of the baseline app.
