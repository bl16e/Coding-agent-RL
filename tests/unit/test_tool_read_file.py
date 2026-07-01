from pathlib import Path

from coding_agent.tools.read_file import read_file


def test_read_file_returns_file_content(tmp_path: Path):
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")

    result = read_file(tmp_path, {"path": "README.md"})

    assert result.status == "ok"
    assert result.output["content"] == "hello\n"


def test_read_file_returns_requested_line_range(tmp_path: Path):
    (tmp_path / "README.md").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = read_file(tmp_path, {"path": "README.md", "line": 2, "end_line": 3})

    assert result.status == "ok"
    assert result.output["content"] == "two\nthree\n"
    assert "lines 2-3" in result.output_summary


def test_read_file_treats_offset_limit_as_line_window(tmp_path: Path):
    (tmp_path / "README.md").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = read_file(tmp_path, {"path": "README.md", "offset": 2, "limit": 2})

    assert result.status == "ok"
    assert result.output["content"] == "two\nthree\n"
    assert "lines 2-3" in result.output_summary


def test_read_file_treats_line_limit_as_line_window(tmp_path: Path):
    (tmp_path / "README.md").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = read_file(tmp_path, {"path": "README.md", "line": 2, "limit": 2})

    assert result.status == "ok"
    assert result.output["content"] == "two\nthree\n"
    assert "lines 2-3" in result.output_summary


def test_read_file_reports_missing_file(tmp_path: Path):
    result = read_file(tmp_path, {"path": "missing.py"})

    assert result.status == "failed"
    assert "not found" in result.output_summary


def test_read_file_rejects_outside_workspace(tmp_path: Path):
    result = read_file(tmp_path, {"path": "../outside.py"})

    assert result.status == "rejected"
    assert "escapes workspace" in result.output_summary
