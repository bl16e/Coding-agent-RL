from pathlib import Path

from coding_agent.tools.write_file import write_file


def test_write_file_writes_complete_content(tmp_path: Path):
    result = write_file(tmp_path, {"path": "src/app.py", "content": "print('new')\n"})

    assert result.status == "ok"
    assert (tmp_path / "src" / "app.py").read_text(encoding="utf-8") == "print('new')\n"
    assert result.modifications[0].path == "src/app.py"


def test_write_file_rejects_missing_content(tmp_path: Path):
    result = write_file(tmp_path, {"path": "app.py"})

    assert result.status == "rejected"
    assert "complete file content" in result.output_summary


def test_write_file_rejects_outside_workspace(tmp_path: Path):
    result = write_file(tmp_path, {"path": "../outside.py", "content": "bad"})

    assert result.status == "rejected"
    assert not (tmp_path.parent / "outside.py").exists()

