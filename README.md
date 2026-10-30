# OpsPilot — Autonomous AI Operations Engineer

**An AI-powered engineering agent that investigates software failures, identifies root causes, proposes fixes, and verifies them through real test execution—with human approval and rollback safeguards.**

> Built for the **Nebius × NVIDIA Global AI Hackathon 2026**  
> Track: **Coding and Agentic Engineering**

---

## Overview

Software engineers often spend significant time investigating failures, navigating unfamiliar codebases, reproducing bugs, identifying root causes, and validating fixes.

**OpsPilot** aims to streamline this workflow through an autonomous engineering agent.

Given an engineering objective, OpsPilot can:

1. Explore the repository and inspect relevant source files.
2. Execute tests to reproduce and understand failures.
3. Analyze available evidence and identify a likely root cause.
4. Generate a targeted code patch.
5. Request human approval before applying changes.
6. Apply the approved patch using controlled file operations.
7. Execute tests again to verify the result.
8. Roll back the changes if verification fails.
9. Produce an investigation report with evidence and execution status.

The goal is not simply to generate code, but to build an engineering workflow where every proposed change is controlled and its outcome is verified.

## Key Features

### 1. Autonomous Investigation

OpsPilot accepts an engineering objective and investigates the repository using bounded tools.

It can:
- List repository files.
- Read relevant source files.
- Execute automated tests.
- Collect execution results.
- Build an evidence-based diagnosis.

### 2. Controlled Tool Execution

The agent does not receive unrestricted access to the system.

Its available operations are explicitly bounded, with safeguards such as:
- Restricted file access.
- Limited investigation scope.
- Test execution timeouts.
- Controlled patch locations.
- Validation of tool requests.

### 3. AI-Powered Root Cause Analysis

OpsPilot uses a model-driven investigation workflow to interpret repository information, test results, and execution evidence.

The model is responsible for reasoning about the engineering problem and proposing the next action.

### 4. Human-in-the-Loop Code Changes

Code modifications are not applied automatically without authorization.

OpsPilot presents a proposed patch and requires human approval before applying it.

This keeps engineers in control of potentially risky changes.

### 5. Automated Verification

After applying an approved patch, OpsPilot executes the test suite again.

It distinguishes between:
- **Verified:** The required tests pass after the change.
- **Not Verified:** Tests fail, execution is incomplete, or the result cannot be established.

### 6. Automatic Rollback

If a patch causes verification to fail, OpsPilot restores the original file contents.

This prevents an unsuccessful automated fix from being treated as a successful outcome.

### 7. Multiple Model Providers

The application is designed around a configurable model-provider layer.

Supported or integrated provider options include:

| Provider | Purpose |
|---|---|
| Nebius Token Factory | Intended inference provider with NVIDIA Nemotron |
| Mock Provider | Offline demonstration and deterministic testing |
| Google Gemini | Optional development integration |

The active provider and model should be visible in the application.

## Architecture

```text
                  ┌────────────────────────┐
                  │      React UI          │
                  │ Investigation Dashboard│
                  └───────────┬────────────┘
                              │
                              ▼
                  ┌────────────────────────┐
                  │       FastAPI          │
                  │     Backend API        │
                  └───────────┬────────────┘
                              │
                              ▼
                  ┌────────────────────────┐
                  │ Investigation Loop     │
                  │ Agent Orchestrator     │
                  └───────────┬────────────┘
                              │
                  ┌───────────┴────────────┐
                  ▼                        ▼
         ┌─────────────────┐      ┌─────────────────┐
         │  Model Client   │      │ Investigation   │
         │                 │      │ Tools            │
         └────────┬────────┘      └────────┬────────┘
                  │                        │
          ┌───────┴────────┐        ┌───────┼────────┐
          ▼                ▼        ▼       ▼        ▼
      Nebius API       Mock Model  List   Read     Run
      Nemotron                    Files  Files   Tests
                  │
                  ▼
         ┌───────────────────┐
         │   Patch Manager   │
         │ Approval / Apply  │
         │ Rollback / Verify │
         └───────────────────┘
```

### Main Components

| Component | Responsibility |
|---|---|
| React Frontend | Investigation dashboard, provider configuration, progress, and results |
| FastAPI Backend | Exposes backend functionality to the frontend |
| Investigation Loop | Coordinates agent decisions, tool calls, and execution limits |
| Model Client | Connects the application to the configured model provider |
| Investigation Tools | Provides bounded repository inspection and test execution |
| Patch Manager | Handles controlled modifications, approval, and rollback |
| Test Runner | Executes tests and collects verification results |

## Technology Stack

- **Frontend:** React
- **Backend API:** Python, FastAPI
- **Agent Orchestration:** Python
- **AI Model:** NVIDIA Nemotron 3 Super (intended through Nebius Token Factory)
- **Model Integration:** OpenAI-compatible API client
- **Testing:** pytest
- **Version Control:** Git

## Investigation Workflow

The following is the intended end-to-end workflow:

```text
Engineering Objective
        |
        v
Repository Exploration
        |
        v
Failure Reproduction
        |
        v
Evidence Collection
        |
        v
Root Cause Diagnosis
        |
        v
Patch Proposal
        |
        v
Human Approval
        |
        v
Controlled Patch Application
        |
        v
Automated Test Execution
        |
   +----+----+
   |         |
  Pass      Fail
   |         |
   v         v
Verified   Rollback
             |
             v
        Not Verified
```

## Example Demonstration

**Investigation objective:**

> Investigate why the `/api/users` endpoint returns HTTP 500 and fix the root cause.

OpsPilot demonstrates the following process:

1. Inspects the application source code.
2. Executes the test suite and identifies the failing endpoint test.
3. Analyzes the failure and identifies the intentional defect.
4. Proposes a targeted patch.
5. Waits for human approval.
6. Applies the patch.
7. Runs the tests again.
8. Reports the verification result.

A separate failure scenario demonstrates how OpsPilot handles an unsuccessful patch by restoring the original file and reporting that the issue is not verified.

## Model Integration and Demo Modes

OpsPilot separates model reasoning from the execution of engineering tools.

### Nebius Token Factory — NVIDIA Nemotron

The project includes a configurable Nebius Token Factory client intended to use NVIDIA Nemotron 3 Super.

The intended model configuration is:

`nvidia/nemotron-3-super-120b-a12b`

**Integration status:** The Nebius client and provider configuration are implemented. However, live inference through Nebius Token Factory was not successfully verified during hackathon development because account billing onboarding prevented access to the required API credentials.

### Mock Mode — Offline Demonstration

Mock mode allows the complete engineering workflow to be demonstrated without a live model API connection.

Important distinction:

- Repository inspection uses real tool operations.
- Test execution runs the actual pytest suite.
- File modifications and rollback use the actual patch-management implementation.
- Model decisions in Mock mode are simulated using a deterministic rule-based implementation.

Mock mode is therefore an offline demonstration of the execution workflow, not evidence of live AI inference.

## Safety and Reliability

OpsPilot is designed with safeguards around automated engineering operations.

- **Bounded tools:** The agent can only use explicitly available operations.
- **Restricted modifications:** Patch operations are limited to approved paths.
- **Human approval:** Changes require authorization before application.
- **Atomic patching:** File modifications are applied through controlled operations.
- **Test-based verification:** Changes are evaluated using actual test execution.
- **Rollback:** Failed verification restores the original contents.
- **Explicit status:** Unverified changes are never reported as successful fixes.

## Getting Started

### Prerequisites

- Python 3.10+ (adjust if your project uses a different version)
- Node.js and npm
- Git

### 1. Clone the repository

```bash
git clone <YOUR_PUBLIC_REPOSITORY_URL>
cd <YOUR_PROJECT_DIRECTORY>
```

### 2. Backend setup

```bash
python -m venv venv
```

Activate the environment:

**Windows PowerShell**

```powershell
.\venv\Scripts\Activate.ps1
```

**Linux/macOS**

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file using the environment variables supported by your implementation.

For Nebius integration, configure:

```env
NEBIUS_API_KEY=your_nebius_api_key
```

Do not commit API keys or other credentials to GitHub.

### 4. Start the backend

Use the actual FastAPI application entrypoint in your repository. For example:

```bash
uvicorn main:app --reload
```

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open the local frontend URL printed by Vite.

> Update the commands above if your actual repository uses different directory names or application entrypoints.

## Running Tests

Run the test suite:

```bash
python -m pytest -q
```

The investigation workflow also uses test execution to evaluate whether a proposed patch resolves the failure.

## Repository Structure

The logical project structure is:

```text
OpsPilot/
│
├── frontend/                 # React application
│
├── backend/                  # FastAPI application (if separated)
│
├── investigation_loop.py     # Agent orchestration
├── investigation_tools.py    # Bounded investigation tools
├── patch_tools.py            # Patch application and rollback
├── model_client.py           # Nebius/model provider client
├── mock_model.py             # Offline deterministic model
├── demo.py                   # Terminal demonstration
│
├── tests/                    # Automated tests
│
├── requirements.txt
├── README.md
└── LICENSE
```

> The structure above describes the main logical components. Adapt it to match the actual files and folders in the published repository.

## Current Limitations

- Live Nebius Token Factory inference has not yet been verified.
- Mock mode uses deterministic, rule-based decisions rather than live model reasoning.
- The investigation tools operate within a controlled scope and are not intended to replace unrestricted production debugging.
- Patch application is limited to the paths and operations explicitly allowed by the implementation.

These limitations are stated explicitly to distinguish implemented functionality from capabilities that still require live validation.

## Future Roadmap

- Complete and validate live Nebius Token Factory inference.
- Expand support for repository types and programming languages.
- Add richer investigation memory and evidence tracking.
- Improve patch generation and multi-file change handling.
- Add CI/CD integration.
- Introduce configurable approval policies.
- Support additional engineering workflows such as security investigation and automated regression analysis.

## Hackathon Submission

**Event:** Nebius × NVIDIA Global AI Hackathon 2026  
**Project:** OpsPilot — Autonomous AI Operations Engineer  
**Track:** Coding and Agentic Engineering  
**Model:** NVIDIA Nemotron 3 Super (intended Nebius Token Factory integration)

## License

This project is released under the **MIT License**. See the `LICENSE` file for details.

---

**OpsPilot — From investigation to verified engineering action.**