from pathlib import Path

from coding_agent.trajectory.patch import generate_unified_patch, snapshot_workspace
from coding_agent.swebench.sandbox_run import filter_validation_patch_changes


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


def test_filter_validation_patch_changes_removes_test_patch_files():
    final_patch = "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "diff --git a/tests/test_issue.py b/tests/test_issue.py",
            "--- a/tests/test_issue.py",
            "+++ b/tests/test_issue.py",
            "@@ -1 +1 @@",
            "-old test",
            "+new test",
            "",
        ]
    )
    test_patch = "\n".join(
        [
            "diff --git a/tests/test_issue.py b/tests/test_issue.py",
            "--- a/tests/test_issue.py",
            "+++ b/tests/test_issue.py",
            "@@ -1 +1 @@",
            "-old test",
            "+new test",
            "",
        ]
    )

    filtered = filter_validation_patch_changes(final_patch, test_patch)

    assert "diff --git a/app.py b/app.py" in filtered
    assert "tests/test_issue.py" not in filtered


def test_filter_validation_patch_changes_keeps_patch_when_no_test_patch():
    final_patch = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"

    assert filter_validation_patch_changes(final_patch, "") == final_patch
