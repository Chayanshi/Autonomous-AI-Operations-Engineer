# Targets

Each folder here is a small, self-contained repository that the agent investigates and repairs. The agent's own code lives in `backend/` and is never visible to it: `list_files`, `read_file` and `run_tests` only operate inside the selected target folder.

| Target | What the user sees | Root cause (for the agent to find) | Evidence the agent gets | Correct fix | Wrong fix (rollback demo) |
|---|---|---|---|---|---|
| `users_api` | `GET /api/users` always fails with HTTP 500 | The handler unconditionally raises `HTTPException(500)` | `assert 500 == 200` | Return `{"users": []}` | Return `{}` |
| `config_service` | Service crashes on startup when `PAGE_SIZE` is not set | `int(os.environ["PAGE_SIZE"])` at import; the `DEFAULT_PAGE_SIZE` constant is never used | `KeyError: 'PAGE_SIZE'` | `os.environ.get("PAGE_SIZE", DEFAULT_PAGE_SIZE)` | `os.environ.get("PAGE_SIZE")` → `int(None)` still crashes |
| `pagination_api` | No error, but pages have 2 items instead of 3 | Off-by-one slice `[offset : offset + limit - 1]` | `assert [1, 2] == [1, 2, 3]` | `[offset : offset + limit]` | `[offset : offset + limit + 1]` → 4 items |
| `profile_api` | HTTP 500 only for users without an email | `user["email"].lower()` on a `None` email | `AttributeError: 'NoneType' object has no attribute 'lower'` | Lower-case only when present, keep `None` | `(email or "").lower()` → returns `""`, but `None` is expected |

The targets with a second, already-passing test (`config_service`, `profile_api`) also show that a fix must not break working behaviour.

## How the mock recognises each bug

`backend/mock_model.py` has one rule per bug type. A rule fires only when **both** the source code and the captured test output support it, and the text to replace must appear exactly once. If no rule matches, the mock says the cause is not identified and proposes nothing; it never guesses. Every rule also has a deliberately wrong fix, used by the *Wrong fix* scenario to demonstrate rollback.

## Select a target

Pick one in the UI's **Target app** list, or use `python demo.py --target <name>` in the terminal. `OPSPILOT_TARGET` sets the default. Names must be plain folder names (letters, digits, `_`, `-`); paths like `../backend` are rejected.

## Add a new target

1. Create `targets/<name>/app.py` and `targets/<name>/tests/test_app.py`.
2. Write tests for the **healthy** behaviour and leave the bug in place, so the target's own suite fails at baseline.
3. Check that `python -m pytest -q`, run inside the folder, reproduces the failure in a few seconds.
4. Add a title, symptom and objective in `backend/target_catalog.py`. Describe the symptom, not the cause.
5. Commit it (or at least `git add` it). **Reset targets** restores files with `git checkout`, which only works for files git knows about.
6. For mock mode, add a rule in `backend/mock_model.py` plus a case in `backend/tests/test_end_to_end_mock.py`. Live mode needs no rule.

Current limitation: the editable file is always `app.py` (`PATCH_PATH` in `backend/server.py` and `backend/demo.py`).
