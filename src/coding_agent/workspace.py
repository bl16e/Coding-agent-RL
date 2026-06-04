from __future__ import annotations

from pathlib import Path


class WorkspacePathError(ValueError):
    pass


def ensure_workspace_dir(workspace: str | Path) -> Path:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise WorkspacePathError(f"workspace does not exist or is not a directory: {workspace}")
    return root


def _assert_inside(workspace: Path, candidate: Path) -> Path:
    root = ensure_workspace_dir(workspace)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspacePathError(f"path escapes workspace: {candidate}") from exc
    return resolved


def resolve_workspace_path(workspace: str | Path, requested_path: str | Path) -> Path:
    root = ensure_workspace_dir(workspace)
    requested = Path(requested_path)
    candidate = requested if requested.is_absolute() else root / requested
    return _assert_inside(root, candidate)


def to_workspace_relative(workspace: str | Path, path: str | Path) -> str:
    root = ensure_workspace_dir(workspace)
    resolved = _assert_inside(root, Path(path))
    return resolved.relative_to(root).as_posix()

