# Autonomous AI Operations Engineer

## Set up on Windows

From the project directory, create and activate a virtual environment, then install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Run the tests:

```powershell
python -m pytest
```

The `/api/users` test is expected to fail at baseline because the endpoint intentionally raises an HTTP 500 error.

Run the application locally:

```powershell
python -m uvicorn app:app --reload
```

Open <http://127.0.0.1:8000/api/users> to see the endpoint response.

## Model-driven investigation

The investigator uses Nebius Token Factory with NVIDIA Nemotron 3 Super. Copy `.env.example` to `.env` and add your `NEBIUS_API_KEY`. The client loads `.env` automatically; `.env` is ignored by Git. The optional `NEBIUS_BASE_URL` and `NEBIUS_MODEL` variables override the documented defaults.

Run an investigation from the project directory:

```powershell
python -c "import json; from investigation_loop import investigate_objective; print(json.dumps(investigate_objective('Investigate why /api/users returns HTTP 500'), indent=2))"
```

By default, the model can only list files, read repository files through the bounded reader, and run the predefined pytest command. To enable a single, exact-text patch for one explicitly authorized Python path, pass `allowed_patch_paths={"app.py"}` to `investigate_objective`. A patch immediately runs the fixed pytest command and is rolled back if tests fail or time out. The intentional `/api/users` baseline remains unchanged unless you explicitly authorize `app.py` in an investigation.

Run the automated tests with `python -m pytest`; the intentional `/api/users` baseline test is expected to fail until that fix is separately authorized and verified.
