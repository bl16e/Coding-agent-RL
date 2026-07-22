from pathlib import Path

import subprocess

# REMOVED: trajectory.patch deleted
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


def test_generate_workspace_patch_uses_git_diff_binary_for_git_repo(tmp_path: Path):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"diff --git a/app.py b/app.py\n", stderr=b"")

    patch = generate_workspace_patch(tmp_path, {"app.py": "old\n"}, {"app.py": "new\n"}, runner=fake_run)

    assert patch == "diff --git a/app.py b/app.py\n"
    assert calls[0][:3] == ["git", "-C", str(tmp_path.resolve())]
    assert "--binary" in calls[0]


def test_generate_workspace_patch_falls_back_to_snapshot_diff_when_git_diff_fails(tmp_path: Path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 129, stdout=b"", stderr=b"not a git repo")

    patch = generate_workspace_patch(tmp_path, {"app.py": "old\n"}, {"app.py": "new\n"}, runner=fake_run)

    assert "--- a/app.py" in patch
    assert "+new" in patch


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
