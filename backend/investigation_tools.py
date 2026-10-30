"""Bounded, read-only repository inspection and test capabilities."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


TARGETS_DIR = Path(__file__).resolve().parent.parent / "targets"
DEFAULT_TARGET = "users_api"


def target_root(name: str) -> Path:
    """Resolve a target repository by folder name under targets/ (operator configuration only)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Target name must be a plain folder name under targets/")
    return TARGETS_DIR / name


def available_targets() -> list[str]:
    """Target folders that contain an app.py, sorted by name."""
    if not TARGETS_DIR.is_dir():
        return []
    return sorted(
        path.name
        for path in TARGETS_DIR.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and re.fullmatch(r"[A-Za-z0-9_-]+", path.name)
        and (path / "app.py").is_file()
    )


# The repository the agent investigates. The agent's own code is never inside it.
TARGET_NAME = os.environ.get("OPSPILOT_TARGET", DEFAULT_TARGET)
PROJECT_ROOT = target_root(TARGET_NAME)
MAX_FILE_SIZE_BYTES = 1_048_576
TEST_TIMEOUT_SECONDS = 120

_IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "htmlcov",
    "node_modules",
    "venv",
}


@dataclass(frozen=True)
class TestRunResult:
    """Captured result of the one allowed test command."""

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool


def _repository_root() -> Path:
    root = PROJECT_ROOT.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Repository root is not a directory: {root}")
    return root


def list_files() -> list[str]:
    """List regular project files relative to the repository root."""
    root = _repository_root()
    result: list[str] = []

    for current_dir, directory_names, file_names in os.walk(root, topdown=True):
        current = Path(current_dir)
        directory_names[:] = [
            name
            for name in directory_names
            if name.lower() not in _IGNORED_DIRECTORY_NAMES
            and not name.lower().endswith(".egg-info")
            and not (current / name).is_symlink()
        ]

        for name in file_names:
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            result.append(path.relative_to(root).as_posix())

    return sorted(result)


def read_file(relative_path: str) -> str:
    """Read a UTF-8 file within the repository, up to one MiB."""
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("A non-empty relative file path is required")

    windows_path = PureWindowsPath(relative_path)
    posix_path = PurePosixPath(relative_path)
    path_parts = relative_path.replace("\\", "/").split("/")
    if (
        windows_path.is_absolute()
        or windows_path.drive
        or posix_path.is_absolute()
        or any(part == ".." for part in path_parts)
        or "\x00" in relative_path
    ):
        raise ValueError("Path must be relative and must not traverse directories")

    root = _repository_root()
    candidate = root.joinpath(*[part for part in path_parts if part not in ("", ".")])
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise

    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("Path resolves outside the repository") from error

    if not resolved.is_file():
        raise ValueError("Path does not refer to a regular file")
    if resolved.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File exceeds the {MAX_FILE_SIZE_BYTES}-byte limit")

    content = resolved.read_bytes()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File exceeds the {MAX_FILE_SIZE_BYTES}-byte limit")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("File is not valid UTF-8 text") from error


def _captured_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_tests() -> TestRunResult:
    """Run only this project's fixed pytest command, with a hard timeout."""
    root = _repository_root()
    command = [sys.executable, "-m", "pytest", "-q"]
    # Plain text output: colour codes would corrupt evidence parsing and the report.
    environment = {key: value for key, value in os.environ.items() if key not in {"FORCE_COLOR", "PY_COLORS"}}
    environment["PY_COLORS"] = "0"
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        return TestRunResult(
            stdout=_captured_text(error.stdout),
            stderr=_captured_text(error.stderr),
            exit_code=None,
            timed_out=True,
        )

    return TestRunResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        timed_out=False,
    )
