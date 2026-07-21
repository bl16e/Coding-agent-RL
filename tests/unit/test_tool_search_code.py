from pathlib import Path

from coding_agent.tools.search_code import search_code


def test_search_code_finds_utf8_chinese_text_and_reports_file_metadata(tmp_path: Path):
    (tmp_path / "notes.md").write_bytes("标题\n正文 needle\n".encode("utf-8"))

    result = search_code(tmp_path, {"query": "正文"})

    assert result.status == "ok"
    assert result.output["matches"] == [
        {"path": "notes.md", "line": 2, "text": "正文 needle", "encoding": "utf-8", "newline": "lf"}
    ]


def test_search_code_finds_gbk_text_without_reencoding(tmp_path: Path):
    (tmp_path / "legacy.txt").write_bytes("第一行\r\n中文 needle\r\n".encode("gbk"))

    result = search_code(tmp_path, {"query": "中文"})

    assert result.status == "ok"
    assert result.output["matches"] == [
        {"path": "legacy.txt", "line": 2, "text": "中文 needle", "encoding": "gbk", "newline": "crlf"}
    ]


def test_search_code_skips_binary_files_and_reports_count(tmp_path: Path):
    (tmp_path / "image.bin").write_bytes(b"\x00needle\x00")

    result = search_code(tmp_path, {"query": "needle"})

    assert result.status == "ok"
    assert result.output["matches"] == []
    assert result.output["binary_skipped"] == 1


def test_search_code_returns_bounded_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\nneedle\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("needle\n", encoding="utf-8")

    result = search_code(tmp_path, {"query": "needle", "max_results": 2})

    assert result.status == "ok"
    assert len(result.output["matches"]) == 2
    assert result.output["truncated"] is True


def test_search_code_reports_no_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("hay\n", encoding="utf-8")

    result = search_code(tmp_path, {"query": "needle"})

    assert result.status == "ok"
    assert result.output["matches"] == []


def test_search_code_treats_query_as_regular_expression(tmp_path: Path):
    (tmp_path / "models.py").write_bytes(b"class CharField(Field):\nclass Other:\n")

    result = search_code(tmp_path, {"query": r"^class CharField\(Field\):"})

    assert result.status == "ok"
    assert result.output["matches"] == [
        {"path": "models.py", "line": 1, "text": "class CharField(Field):", "encoding": "utf-8", "newline": "lf"}
    ]


def test_search_code_rejects_invalid_regular_expression(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")

    result = search_code(tmp_path, {"query": "["})

    assert result.status == "rejected"
    assert "invalid regular expression" in result.output_summary


def test_search_code_rejects_empty_query(tmp_path: Path):
    result = search_code(tmp_path, {"query": ""})

    assert result.status == "rejected"
