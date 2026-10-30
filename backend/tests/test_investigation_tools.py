from pathlib import Path
import subprocess

import pytest

import investigation_tools
from investigation_tools import (
    MAX_FILE_SIZE_BYTES,
    TEST_TIMEOUT_SECONDS,
    list_files,
    read_file,
    run_tests,
)


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_list_files_returns_relative_files_and_skips_irrelevant_directories(
    repository: Path,
) -> None:
    (repository / "app.py").write_text("app", encoding="utf-8")
    (repository / "src").mkdir()
    (repository / "src" / "module.py").write_text("module", encoding="utf-8")
    for directory in (".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"):
        ignored = repository / directory
        ignored.mkdir()
        (ignored / "hidden.txt").write_text("hidden", encoding="utf-8")

    assert list_files() == ["app.py", "src/module.py"]


def test_read_file_reads_repository_file(repository: Path) -> None:
    (repository / "app.py").write_bytes(b"print('hello')\n")

    assert read_file("app.py") == "print('hello')\n"


@pytest.mark.parametrize("path", ["../outside.txt", "nested/../../outside.txt", "C:\\outside.txt", "\\\\server\\share\\file"])
def test_read_file_rejects_absolute_paths_and_traversal(repository: Path, path: str) -> None:
    with pytest.raises(ValueError):
        read_file(path)


def test_read_file_rejects_symlink_resolving_outside_repository(
    repository: Path, tmp_path: Path
) -> None:
    outside_file = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside_file.write_text("secret", encoding="utf-8")
    link = repository / "outside-link.txt"
    try:
        link.symlink_to(outside_file)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symlink creation is unavailable: {error}")

    with pytest.raises(ValueError, match="outside the repository"):
        read_file("outside-link.txt")


def test_read_file_enforces_maximum_size(repository: Path) -> None:
    (repository / "large.txt").write_bytes(b"x" * (MAX_FILE_SIZE_BYTES + 1))

    with pytest.raises(ValueError, match="exceeds"):
        read_file("large.txt")


def test_run_tests_runs_fixed_pytest_command_and_captures_output(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 2, "pytest stdout", "pytest stderr")

    monkeypatch.setattr(investigation_tools.subprocess, "run", fake_run)
    result = run_tests()

    assert result.stdout == "pytest stdout"
    assert result.stderr == "pytest stderr"
    assert result.exit_code == 2
    assert result.timed_out is False
    assert observed["command"] == [investigation_tools.sys.executable, "-m", "pytest", "-q"]
    assert observed["cwd"] == repository
    assert observed["timeout"] == TEST_TIMEOUT_SECONDS
    assert observed["shell"] is False


def test_run_tests_reports_timeout(repository: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"partial", stderr=b"stalled")

    monkeypatch.setattr(investigation_tools.subprocess, "run", fake_run)
    result = run_tests()

    assert result.stdout == "partial"
    assert result.stderr == "stalled"
    assert result.exit_code is None
    assert result.timed_out is True


def test_run_tests_does_not_accept_arbitrary_commands() -> None:
    with pytest.raises(TypeError):
        run_tests("python -c 'do anything'")  # type: ignore[call-arg]


def test_default_target_is_separate_from_the_agent_code() -> None:
    agent_dir = Path(investigation_tools.__file__).resolve().parent

    assert investigation_tools.PROJECT_ROOT == investigation_tools.TARGETS_DIR / "users_api"
    assert agent_dir not in investigation_tools.PROJECT_ROOT.resolve().parents
    assert (investigation_tools.PROJECT_ROOT / "app.py").is_file()


@pytest.mark.parametrize("name", ["../backend", "users_api/../..", "C:\temp", "", "a b"])
def test_target_names_cannot_escape_the_targets_folder(name: str) -> None:
    with pytest.raises(ValueError, match="plain folder name"):
        investigation_tools.target_root(name)
