from pathlib import Path

import pytest

import investigation_tools
import patch_tools


def test_exact_text_patch_and_restore_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)
    target = tmp_path / "app.py"
    original = 'def status():\n    return 500\n'
    target.write_text(original, encoding="utf-8")

    result, snapshot = patch_tools.apply_text_replacement(
        "app.py", "return 500", "return 200", {"app.py"}
    )

    assert target.read_text(encoding="utf-8") == 'def status():\n    return 200\n'
    assert result.relative_path == "app.py"
    assert result.original_sha256 != result.updated_sha256
    patch_tools.restore_patch(snapshot)
    assert target.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("path", "expected", "replacement", "allowed", "message"),
    [
        ("../outside.py", "x", "y", {"../outside.py"}, "authorized repository-relative"),
        ("app.py", "return 1", "return 2", set(), "not explicitly authorized"),
        ("README.md", "x", "y", {"README.md"}, "authorized repository-relative"),
        ("app.py", "return 9", "return 2", {"app.py"}, "exactly once"),
        ("app.py", "return 1", "return 2", {"app.py"}, "exactly once"),
    ],
)
def test_patch_rejects_unsafe_or_stale_replacements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    expected: str,
    replacement: str,
    allowed: set[str],
    message: str,
) -> None:
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)
    (tmp_path / "app.py").write_text("return 1\nreturn 1", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        patch_tools.apply_text_replacement(path, expected, replacement, allowed)


def test_patch_refuses_to_restore_over_a_later_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(investigation_tools, "PROJECT_ROOT", tmp_path)
    target = tmp_path / "app.py"
    target.write_text("return 1", encoding="utf-8")
    _, snapshot = patch_tools.apply_text_replacement("app.py", "1", "2", {"app.py"})
    target.write_text("return 3", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        patch_tools.restore_patch(snapshot)
    assert target.read_text(encoding="utf-8") == "return 3"
