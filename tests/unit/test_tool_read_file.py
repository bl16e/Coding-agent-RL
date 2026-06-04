from pathlib import Path

from coding_agent.tools.read_file import read_file


def test_read_file_returns_file_content(tmp_path: Path):
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")

    result = read_file(tmp_path, {"path": "README.md"})

    assert result.status == "ok"
    assert result.output["content"] == "hello\n"


def test_read_file_reports_missing_file(tmp_path: Path):
    result = read_file(tmp_path, {"path": "missing.py"})

    assert result.status == "failed"
    assert "not found" in result.output_summary


def test_read_file_rejects_outside_workspace(tmp_path: Path):
    result = read_file(tmp_path, {"path": "../outside.py"})

    assert result.status == "rejected"
    assert "escapes workspace" in result.output_summary

