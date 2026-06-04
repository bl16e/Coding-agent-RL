from pathlib import Path

from coding_agent.trajectory.patch import generate_unified_patch, snapshot_workspace


def test_generate_unified_patch_for_changed_file():
    patch = generate_unified_patch(
        before={"app.py": "print('old')\n"},
        after={"app.py": "print('new')\n"},
    )

    assert "--- a/app.py" in patch
    assert "+++ b/app.py" in patch
    assert "-print('old')" in patch
    assert "+print('new')" in patch


def test_snapshot_workspace_uses_relative_text_paths(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")

    snapshot = snapshot_workspace(tmp_path)

    assert snapshot == {"src/app.py": "print('ok')\n"}

