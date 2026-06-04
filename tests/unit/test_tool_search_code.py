from pathlib import Path

from coding_agent.tools.search_code import search_code


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


def test_search_code_rejects_empty_query(tmp_path: Path):
    result = search_code(tmp_path, {"query": ""})

    assert result.status == "rejected"

