from pathlib import Path

from coding_agent.tools.read_file import read_file


def test_read_file_returns_content_with_line_numbers(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"hello\n")

    result = read_file(tmp_path, {"file_path": "README.md"})

    assert result.status == "ok"
    # cat -n format: right-aligned number (min width 4), tab, content
    assert result.output["content"] == "   1\thello\n"
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"
    assert result.output["line_start"] == 1
    assert result.output["line_end"] == 1
    assert result.output["total_lines"] == 1


def test_read_file_returns_utf8_chinese_file_with_line_numbers(tmp_path: Path):
    (tmp_path / "notes.md").write_bytes("标题\n正文\n".encode("utf-8"))

    result = read_file(tmp_path, {"file_path": "notes.md"})

    assert result.status == "ok"
    assert result.output["content"] == "   1\t标题\n   2\t正文\n"
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"
    assert result.output["line_start"] == 1
    assert result.output["line_end"] == 2
    assert result.output["total_lines"] == 2


def test_read_file_reads_gbk_file_without_reencoding(tmp_path: Path):
    (tmp_path / "encoded.txt").write_bytes("中文\n".encode("gbk"))

    result = read_file(tmp_path, {"file_path": "encoded.txt"})

    assert result.status == "ok"
    assert "中文" in result.output["content"]
    assert result.output["encoding"] == "gbk"
    assert result.output["newline"] == "lf"


def test_read_file_rejects_binary_file(tmp_path: Path):
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02\x03")

    result = read_file(tmp_path, {"file_path": "image.bin"})

    assert result.status == "failed"
    assert "binary" in result.output_summary


def test_read_file_pages_large_file_by_default(tmp_path: Path):
    # default limit is 200 lines
    (tmp_path / "large.txt").write_bytes("".join(f"line {idx}\n" for idx in range(1, 501)).encode("utf-8"))

    result = read_file(tmp_path, {"file_path": "large.txt"})

    assert result.status == "ok"
    assert result.output["truncated"] is True
    assert result.output["line_start"] == 1
    assert result.output["line_end"] == 200
    assert result.output["total_lines"] == 500
    assert "truncated" in result.output["content"]


def test_read_file_truncates_very_long_line_by_default(tmp_path: Path):
    (tmp_path / "large.txt").write_text("a" * 60000, encoding="utf-8")

    result = read_file(tmp_path, {"file_path": "large.txt"})

    assert result.status == "ok"
    assert len(result.output["content"]) <= 50000 + 50  # allow for line number and truncation message
    assert result.output["truncated"] is True
    assert result.output["total_lines"] == 1


def test_read_file_returns_requested_line_range(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"one\ntwo\nthree\n")

    result = read_file(tmp_path, {"file_path": "README.md", "offset": 2})

    assert result.status == "ok"
    assert "two" in result.output["content"]
    assert "three" in result.output["content"]
    assert "lines 2-3" in result.output_summary


def test_read_file_reports_missing_file(tmp_path: Path):
    result = read_file(tmp_path, {"file_path": "missing.py"})

    assert result.status == "failed"
    assert "not found" in result.output_summary


def test_read_file_reports_directory_as_error(tmp_path: Path):
    (tmp_path / "subdir").mkdir()

    result = read_file(tmp_path, {"file_path": "subdir"})

    assert result.status == "failed"
    assert "directory" in result.output_summary


def test_read_file_rejects_outside_workspace(tmp_path: Path):
    result = read_file(tmp_path, {"file_path": "../outside.py"})

    assert result.status == "rejected"
    assert "escapes workspace" in result.output_summary


def test_read_file_line_numbers_are_correctly_padded(tmp_path: Path):
    # 100 lines → line numbers should be at least 3 digits wide
    (tmp_path / "many.txt").write_bytes("".join(f"line {idx}\n" for idx in range(1, 101)).encode("utf-8"))

    result = read_file(tmp_path, {"file_path": "many.txt"})

    assert result.status == "ok"
    # First line should have right-aligned 3-digit number, last line too
    assert result.output["content"].startswith("   1\t")
    assert " 100\t" in result.output["content"]


def test_read_file_offset_reads_remaining_lines_with_default_page_size(tmp_path: Path):
    (tmp_path / "data.txt").write_bytes(b"one\ntwo\nthree\n")

    result = read_file(tmp_path, {"file_path": "data.txt", "offset": 2})

    assert result.status == "ok"
    # offset=2 with default 200 lines: reads lines 2-3 (start > 1 means truncated)
    assert "two" in result.output["content"]
    assert "three" in result.output["content"]
    assert "truncated" in result.output["content"]
    assert result.output["line_start"] == 2
    assert result.output["line_end"] == 3
