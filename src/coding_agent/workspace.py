from __future__ import annotations

from pathlib import Path


class WorkspacePathError(ValueError):
    """工具请求路径违反工作区边界时抛出。"""

    pass


def ensure_workspace_dir(workspace: str | Path) -> Path:
    """确认工作区存在并返回绝对路径。"""
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise WorkspacePathError(f"workspace does not exist or is not a directory: {workspace}")
    return root


def _assert_inside(workspace: Path, candidate: Path) -> Path:
    """解析符号链接和相对路径，并拒绝逃出工作区的路径。

    这是本地工具的核心安全边界。即使模型传入绝对路径或带 .. 的路径，也必须在这里
    归一化后再判断是否仍位于 workspace 下。
    """

    root = ensure_workspace_dir(workspace)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspacePathError(f"path escapes workspace: {candidate}") from exc
    return resolved


def resolve_workspace_path(workspace: str | Path, requested_path: str | Path) -> Path:
    """把模型提供的路径解析成经过校验的绝对路径。"""

    root = ensure_workspace_dir(workspace)
    requested = Path(requested_path)
    candidate = requested if requested.is_absolute() else root / requested
    return _assert_inside(root, candidate)


def to_workspace_relative(workspace: str | Path, path: str | Path) -> str:
    """把经过校验的路径转换成产物中使用的 POSIX 相对路径。"""

    root = ensure_workspace_dir(workspace)
    resolved = _assert_inside(root, Path(path))
    return resolved.relative_to(root).as_posix()
