from pathlib import Path

from coding_agent.tools.read_file import read_file


def test_read_file_returns_utf8_chinese_file_with_encoding_metadata(tmp_path: Path):
    (tmp_path / "notes.md").write_bytes("标题\n正文\n".encode("utf-8"))

    result = read_file(tmp_path, {"path": "notes.md"})

    assert result.status == "ok"
    assert result.output["content"] == "标题\n正文\n"
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"
    assert result.output["line_start"] == 1
    assert result.output["line_end"] == 2
    assert result.output["total_lines"] == 2


def test_read_file_reads_gbk_file_without_reencoding(tmp_path: Path):
    (tmp_path / "legacy.txt").write_bytes("中文\n".encode("gbk"))

    result = read_file(tmp_path, {"path": "legacy.txt"})

    assert result.status == "ok"
    assert result.output["content"] == "中文\n"
    assert result.output["encoding"] == "gbk"
    assert result.output["newline"] == "lf"


def test_read_file_rejects_binary_file(tmp_path: Path):
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02\x03")

    result = read_file(tmp_path, {"path": "image.bin"})

    assert result.status == "failed"
    assert "binary" in result.output_summary


def test_read_file_pages_large_file_by_default(tmp_path: Path):
    (tmp_path / "large.txt").write_bytes("".join(f"line {idx}\n" for idx in range(1, 2201)).encode("utf-8"))

    result = read_file(tmp_path, {"path": "large.txt"})

    assert result.status == "ok"
    assert result.output["content"].startswith("line 1\n")
    assert result.output["content"].endswith("line 1000\n")
    assert result.output["truncated"] is True
    assert result.output["line_start"] == 1
    assert result.output["line_end"] == 1000
    assert result.output["total_lines"] == 2200


def test_read_file_truncates_very_long_line_by_default(tmp_path: Path):
    (tmp_path / "large.txt").write_text("a" * 60000, encoding="utf-8")

    result = read_file(tmp_path, {"path": "large.txt"})

    assert result.status == "ok"
    assert len(result.output["content"]) == 50000
    assert result.output["truncated"] is True
    assert result.output["total_lines"] == 1


def test_read_file_returns_file_content(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"hello\n")

    result = read_file(tmp_path, {"path": "README.md"})

    assert result.status == "ok"
    assert result.output["content"] == "hello\n"


def test_read_file_returns_requested_line_range(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"one\ntwo\nthree\n")

    result = read_file(tmp_path, {"path": "README.md", "line": 2, "end_line": 3})

    assert result.status == "ok"
    assert result.output["content"] == "two\nthree\n"
    assert "lines 2-3" in result.output_summary


def test_read_file_treats_offset_limit_as_line_window(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"one\ntwo\nthree\nfour\n")

    result = read_file(tmp_path, {"path": "README.md", "offset": 2, "limit": 2})

    assert result.status == "ok"
    assert result.output["content"] == "two\nthree\n"
    assert "lines 2-3" in result.output_summary


def test_read_file_treats_line_limit_as_line_window(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"one\ntwo\nthree\nfour\n")

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
