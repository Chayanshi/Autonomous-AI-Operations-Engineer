# OpsPilot: Autonomous AI Operations Engineer

An engineering agent that takes an **objective** ("find out why `/api/users` returns 500 and fix it"), investigates a repository with bounded tools, forms an evidence-linked hypothesis and **proposes** a narrowly scoped patch. A human reviews the diff. Only after approval is that exact patch applied, and the real test suite runs again; if any test fails, the change is rolled back automatically. A run is reported as `verified` only when the post-patch tests actually passed.

The apps under `targets/` are only test subjects. Each contains one deliberate, realistic bug: an endpoint that always returns HTTP 500, a crash on startup caused by missing configuration, a silent off-by-one pagination bug, and a 500 error that only affects some records. See [targets/README.md](targets/README.md).

## Repository layout

```
backend/              Python agent, UI API (server.py), terminal demo, and the agent's own tests
frontend/             React + TypeScript UI (Vite)
targets/              Repositories the agent investigates, one folder each (see targets/README.md)
  users_api/          always HTTP 500
  config_service/     crashes when PAGE_SIZE is unset
  pagination_api/     pages one item short (no error)
  profile_api/        HTTP 500 only for users without an email
docs/                 Design notes
```

## Run the web demo

Requires Python 3.11+ and Node 20+.

```powershell
# 1. Backend dependencies
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 2. Build the UI once (from the repository root)
cd ..\frontend
npm install
npm run build

# 3. Start the backend; it also serves the built UI
cd ..\backend
python -m uvicorn server:app --port 8001
```

Open <http://127.0.0.1:8001>.

For UI development with hot reload, keep the backend running and start `npm run dev` in `frontend/`, then open <http://localhost:5173>. Vite proxies `/api` to port 8001.

### Demo script (about 3 minutes)

1. **Correct fix.** Keep *Users API*, *Mock* and *Correct fix*, then click **Run investigation**. The timeline streams each tool call live: list files, read source and test, run pytest (the failure is reproduced). The agent's diagnosis appears, and an **Approval required** card shows the proposed diff. Nothing has been written yet. Click **Approve & verify**: the patch is applied, the full suite runs again, and the run ends **VERIFIED**. The Tests tab shows before (failed) next to after (passed).
2. **Reset targets** in the header restores every target's `app.py` to its broken baseline.
3. **Wrong fix.** Choose *Wrong fix → rollback demo* and approve. Post-patch tests fail, the file is restored, and the run ends **NOT VERIFIED · rolled back**.
4. **Other bugs.** Pick *Products API · pages one item short* (no error, just wrong data) or *Profile API · 500 for some users only*. The diagnosis and fix are different for each target; the note under each choice explains the symptom in plain language.
5. Optionally run again and click **Reject**: nothing is written.

The Guardrails panel shows live usage against the hard limits. *Raw evidence* exposes and downloads the complete report.

### Terminal demo (fallback, no UI needed)

```powershell
cd backend
python demo.py                       # investigate -> patch -> verify (applies without a review pause)
python demo.py --reset               # restore app.py to the committed baseline
python demo.py --scenario bad-patch  # wrong fix -> rolled back
python demo.py --read-only           # diagnosis only
python demo.py --live                # Nebius Token Factory (NEBIUS_API_KEY)
python demo.py --live gemini         # Google Gemini (GEMINI_API_KEY)
python demo.py --target profile_api  # any folder under targets/
```

## AI providers, your own key, and token limits

Click the **✦ button in the bottom-right corner** to see which provider drives the agent and how many tokens this session has used. From there you can switch provider, enter your own API key, test the connection, and set token limits.

| Provider | Who chooses the tool calls | Key | Status |
|---|---|---|---|
| **Mock** (default) | `mock_model.py`: a fixed, rule-based policy | none | Demonstrated in the UI and terminal; covered by end-to-end tests |
| **Google Gemini** | Gemini through its [OpenAI-compatible API](https://ai.google.dev/gemini-api/docs/openai) (default model `gemini-3.8-flash`, editable) | `GEMINI_API_KEY` or enter it in the panel | Implemented and unit-tested with a mocked SDK; **no live call has been demonstrated in this repository yet** |
| **Nebius Token Factory** | NVIDIA Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`, editable) | `NEBIUS_API_KEY` or enter it in the panel | Same as Gemini |

Tools, the patcher, pytest, approval, rollback and the report are real with every provider. Mock mode is clearly labelled everywhere; its output must not be presented as model output.

**Bring your own key.** A key typed into the panel is sent once to the local backend and held **only in that process's memory**. It is never written to disk, never stored in the browser, never returned by the API (the UI only learns whether a key is present and whether it came from you or from `.env`), and it is redacted from evidence and model context exactly like keys from `.env`. Restarting the backend forgets it. Alternatively, set `GEMINI_API_KEY` / `NEBIUS_API_KEY` in `backend/.env` (git-ignored; see `backend/.env.example`). Serve over HTTPS if the backend is ever exposed beyond `localhost`.

**Limits enforced by the server, not the browser:**

- *Max output tokens per model call* (256–8,192) is sent to the provider as `max_tokens`.
- *Token budget per run* (10k–500k, input + output). Once a run has used it, no further model call is made and the run stops with `token_budget`, changing nothing.
- Settings cannot be changed while a run is in progress.
- Usage is counted from what the provider reports. If a provider omits it, the UI shows "not reported" rather than 0.
- There is no dollar spending cap: without reliable per-model pricing it would only be a guess.

**Test connection** sends one tiny request ("Reply with the single word OK.") and reports only success or the error type (for example `AuthenticationError` or `NotFoundError` for a wrong model name), never the provider's raw message.

## How it works

```
React UI ──HTTP/SSE──► server.py ──► investigation_loop ◄──► model (Gemini, Nemotron or mock policy)
                         │                │ validated tool calls
                         │                ├─ investigation_tools: list_files / read_file / run_tests
                         │                └─ apply_text_replacement → PROPOSAL ONLY (validated, not written)
                         │
            human approves the diff
                         └─► apply_approved_patch: write exactly that diff → full pytest → rollback on failure
```

| File | Responsibility |
|---|---|
| `backend/investigation_loop.py` | Bounded model ↔ tool loop, argument validation, redaction, progress events, report, approval-time apply |
| `backend/investigation_tools.py` | Repo-confined file listing/reading and the single fixed pytest command |
| `backend/patch_tools.py` | Exact-text replacement in one authorized file: dry-run validation, atomic write, hash-checked rollback |
| `backend/model_client.py` | OpenAI-compatible chat + tool-calling client for Nebius and Gemini; token usage; output cap |
| `backend/ai_settings.py` | Selected provider, in-memory user keys, limits, session usage; validation |
| `backend/mock_model.py` | Deterministic stand-in for the model when live access is unavailable |
| `backend/server.py` | UI API: runs, server-sent events, approve/reject, reset; one run at a time |
| `backend/demo.py` | Terminal demo |
| `frontend/src/` | UI: run form, live pipeline, guardrails, approval card, diff, tests, raw evidence, AI provider widget |

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Targets and whether each is at baseline, limits |
| `GET /api/settings` · `PUT /api/settings` | Provider, model, key presence (never the key), token limits, usage; `PUT` accepts `{provider, model, api_key, clear_key, max_output_tokens, run_token_budget}`, `409` during a run |
| `POST /api/settings/test` | One minimal request to the selected provider; returns success or the error type |
| `POST /api/runs` | Start a run `{target, objective, scenario, allow_patch}` with the selected provider; `400` without a key, `409` if one is already active |
| `GET /api/runs/{id}/events` | Server-sent event stream of progress (replays from the start; supports `Last-Event-ID`) |
| `POST /api/runs/{id}/approve` · `/reject` | Human decision on the proposed patch |
| `POST /api/reset` | `git checkout -- app.py`; refused while a run is active |

## Safety boundaries

- The model never gets a shell. It can call only `list_files`, `read_file`, `run_tests` and, when authorized, `apply_text_replacement`; names and arguments are validated before execution.
- The browser never supplies file paths, commands or patch text. The only editable file is fixed on the server (`app.py`).
- File reads stay inside the repository (no absolute paths, `..`, or escaping symlinks; 1 MiB cap). `.env`, keys and credential files are never sent to the model.
- `run_tests` runs only `python -m pytest -q` with a 120 s timeout.
- In the UI flow, patches are **proposed, never written by the model's turn**. Approval applies exactly the reviewed text, and is refused if the file changed since the proposal (SHA-256 check).
- After a patch, the full suite runs immediately. Failure or timeout restores the original bytes, and only if the file still matches what the patch wrote.
- `verified` requires an authorized patch, a passing post-patch run, and a completed model turn. Everything else is `not_verified`, `rejected` or `error`.
- Limits: 8 model turns, 20 tool calls, 3 tool errors, 1 patch attempt, 45 s per model request, plus the configurable output-token cap and per-run token budget. Known secrets, including keys entered in the UI, are redacted; provider error details are omitted.

## Tests

```powershell
cd backend
python -m pytest                 # the agent: all tests pass
cd ..\targets\users_api
python -m pytest                 # the target: 1 intentional failure at baseline
cd ..\..\frontend
npm run build                    # type-checks the UI
```

The target's single failing test, the intentional `/api/users` HTTP 500, is left in place deliberately. It is what the agent reproduces, and it passes once the agent's fix is applied. `run_tests` runs only the target's suite, so each verification takes about a second. In `backend/`, `tests/test_end_to_end_mock.py` runs the full workflow (real tools, real pytest subprocess, real patch, approval and rollback) on a temporary copy of the baseline app. `tests/test_server.py` covers the API: the approval gate, rejection, rollback, the one-run lock, validation and event streaming.
