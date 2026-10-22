"""Small, opt-in source edit capability for a single exact text replacement."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import investigation_tools


MAX_PATCH_FILE_BYTES = 1_048_576
MAX_REPLACEMENT_BYTES = 32_768


@dataclass(frozen=True)
class PatchSnapshot:
    relative_path: str
    original_bytes: bytes
    updated_sha256: str


@dataclass(frozen=True)
class PatchResult:
    relative_path: str
    original_sha256: str
    updated_sha256: str


def _resolve_patch_path(relative_path: str, allowed_paths: set[str]) -> Path:
    if relative_path not in allowed_paths:
        raise ValueError("Patch path was not explicitly authorized")
    windows_path = PureWindowsPath(relative_path)
    posix_path = PurePosixPath(relative_path)
    parts = relative_path.replace("\\", "/").split("/")
    if (
        not relative_path
        or windows_path.is_absolute()
        or windows_path.drive
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or "\x00" in relative_path
        or not relative_path.lower().endswith(".py")
    ):
        raise ValueError("Patch path must be an authorized repository-relative Python file")

    root = investigation_tools.PROJECT_ROOT.resolve(strict=True)
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Patch paths cannot contain symlinks")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("Patch path resolves outside the repository") from error
    if not resolved.is_file() or resolved.stat().st_size > MAX_PATCH_FILE_BYTES:
        raise ValueError("Patch target must be a regular file within the size limit")
    return resolved


def apply_text_replacement(
    relative_path: str,
    expected_text: str,
    replacement_text: str,
    allowed_paths: set[str],
) -> tuple[PatchResult, PatchSnapshot]:
    """Replace one unique exact source fragment in an explicitly allowed file."""
    if not isinstance(expected_text, str) or not expected_text:
        raise ValueError("expected_text must be a non-empty string")
    if not isinstance(replacement_text, str) or expected_text == replacement_text:
        raise ValueError("replacement_text must differ from expected_text")
    if len(expected_text.encode("utf-8")) > MAX_REPLACEMENT_BYTES or len(replacement_text.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
        raise ValueError("Patch text exceeds the size limit")

    path = _resolve_patch_path(relative_path, allowed_paths)
    original_bytes = path.read_bytes()
    try:
        original_text = original_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Patch target must be UTF-8 text") from error
    if original_text.count(expected_text) != 1:
        raise ValueError("expected_text must match exactly once in the current file")

    updated_bytes = original_text.replace(expected_text, replacement_text, 1).encode("utf-8")
    if len(updated_bytes) > MAX_PATCH_FILE_BYTES:
        raise ValueError("Updated file exceeds the size limit")
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    updated_hash = hashlib.sha256(updated_bytes).hexdigest()

    descriptor, temporary_name = tempfile.mkstemp(prefix=".ops-patch-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(updated_bytes)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if path.read_bytes() != original_bytes:
            raise RuntimeError("Patch target changed during patch preparation")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    return (
        PatchResult(relative_path, original_hash, updated_hash),
        PatchSnapshot(relative_path, original_bytes, updated_hash),
    )


def restore_patch(snapshot: PatchSnapshot) -> None:
    """Restore only if the file still contains the exact version this patch wrote."""
    path = _resolve_patch_path(snapshot.relative_path, {snapshot.relative_path})
    current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if current_hash != snapshot.updated_sha256:
        raise RuntimeError("Patch target changed after verification; refusing to overwrite it")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".ops-rollback-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(snapshot.original_bytes)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if hashlib.sha256(path.read_bytes()).hexdigest() != snapshot.updated_sha256:
            raise RuntimeError("Patch target changed during rollback preparation")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
