from pathlib import Path

from coding_agent.tools.search_code import search_code


def test_search_code_finds_utf8_text_and_reports_file_metadata(tmp_path: Path):
    (tmp_path / "notes.md").write_bytes("标题\n正文 needle\n".encode("utf-8"))

    result = search_code(tmp_path, {"pattern": "正文"})

    assert result.status == "ok"
    assert result.output["matches"] == [
        {"path": "notes.md", "line": 2, "text": "正文 needle", "encoding": "utf-8", "newline": "lf"}
    ]


def test_search_code_finds_gbk_text_without_reencoding(tmp_path: Path):
    (tmp_path / "legacy.txt").write_bytes("第一行\r\n中文 needle\r\n".encode("gbk"))

    result = search_code(tmp_path, {"pattern": "中文"})

    assert result.status == "ok"
    assert result.output["matches"] == [
        {"path": "legacy.txt", "line": 2, "text": "中文 needle", "encoding": "gbk", "newline": "crlf"}
    ]


def test_search_code_skips_binary_files_and_reports_count(tmp_path: Path):
    (tmp_path / "image.bin").write_bytes(b"\x00needle\x00")

    result = search_code(tmp_path, {"pattern": "needle"})

    assert result.status == "ok"
    assert result.output["matches"] == []
    assert result.output["binary_skipped"] == 1


def test_search_code_returns_bounded_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\nneedle\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("needle\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "needle", "head_limit": 2})

    assert result.status == "ok"
    assert len(result.output["matches"]) == 2
    assert result.output["truncated"] is True


def test_search_code_reports_no_matches(tmp_path: Path):
    (tmp_path / "a.py").write_text("hay\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "needle"})

    assert result.status == "ok"
    assert result.output["matches"] == []


def test_search_code_treats_pattern_as_regular_expression(tmp_path: Path):
    (tmp_path / "models.py").write_bytes(b"class CharField(Field):\nclass Other:\n")

    result = search_code(tmp_path, {"pattern": r"^class CharField\(Field\):"})

    assert result.status == "ok"
    assert result.output["matches"] == [
        {"path": "models.py", "line": 1, "text": "class CharField(Field):", "encoding": "utf-8", "newline": "lf"}
    ]


def test_search_code_rejects_invalid_regular_expression(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "["})

    assert result.status == "rejected"
    assert "invalid regular expression" in result.output_summary


def test_search_code_rejects_empty_pattern(tmp_path: Path):
    result = search_code(tmp_path, {"pattern": ""})

    assert result.status == "rejected"


def test_search_code_ignore_case(tmp_path: Path):
    (tmp_path / "a.py").write_text("Hello World\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "hello", "ignore_case": True})

    assert result.status == "ok"
    assert len(result.output["matches"]) == 1
    assert result.output["matches"][0]["text"] == "Hello World"


def test_search_code_case_sensitive_by_default(tmp_path: Path):
    (tmp_path / "a.py").write_text("Hello World\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "hello"})

    assert result.status == "ok"
    assert result.output["matches"] == []


def test_search_code_glob_filters_files(tmp_path: Path):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("needle\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "needle", "glob": "*.py"})

    assert result.status == "ok"
    assert len(result.output["matches"]) == 1
    assert result.output["matches"][0]["path"] == "a.py"


def test_search_code_glob_nested_directories(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "b.py").write_text("needle\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "needle", "glob": "src/**/*"})

    assert result.status == "ok"
    assert len(result.output["matches"]) == 1
    assert result.output["matches"][0]["path"] == "src/a.py"


def test_search_code_context_around(tmp_path: Path):
    (tmp_path / "a.py").write_text("line1\nline2\nneedle\nline4\nline5\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "needle", "context_around": 1})

    assert result.status == "ok"
    match = result.output["matches"][0]
    assert match["line"] == 3
    assert match["text"] == "needle"
    assert match["context_before"] == [{"line": 2, "text": "line2"}]
    assert match["context_after"] == [{"line": 4, "text": "line4"}]


def test_search_code_context_before_and_after(tmp_path: Path):
    (tmp_path / "a.py").write_text("line1\nline2\nneedle\nline4\nline5\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "needle", "context_before": 2, "context_after": 1})

    assert result.status == "ok"
    match = result.output["matches"][0]
    assert len(match["context_before"]) == 2
    assert match["context_before"][0] == {"line": 1, "text": "line1"}
    assert match["context_before"][1] == {"line": 2, "text": "line2"}
    assert len(match["context_after"]) == 1
    assert match["context_after"][0] == {"line": 4, "text": "line4"}


def test_search_code_excludes_default_dirs(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("needle\n", encoding="utf-8")
    (tmp_path / "src.py").write_text("needle\n", encoding="utf-8")

    result = search_code(tmp_path, {"pattern": "needle"})

    assert result.status == "ok"
    assert len(result.output["matches"]) == 1
    assert result.output["matches"][0]["path"] == "src.py"
