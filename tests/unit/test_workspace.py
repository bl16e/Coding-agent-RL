from pathlib import Path

import pytest

from coding_agent.workspace import WorkspacePathError, resolve_workspace_path, to_workspace_relative


def test_resolve_workspace_path_accepts_relative_paths_inside_workspace(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    resolved = resolve_workspace_path(workspace, "src/app.py")

    assert resolved == workspace / "src" / "app.py"


def test_resolve_workspace_path_rejects_parent_traversal(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    with pytest.raises(WorkspacePathError):
        resolve_workspace_path(workspace, "../outside.py")


def test_to_workspace_relative_rejects_outside_path(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    outside = tmp_path / "outside.py"

    with pytest.raises(WorkspacePathError):
        to_workspace_relative(workspace, outside)

