from pathlib import Path

from coding_agent.tools.apply_patch import apply_patch


def test_apply_patch_preserves_gbk_encoding_on_update(tmp_path: Path):
    path = tmp_path / "legacy.txt"
    path.write_bytes("你好，旧世界\r\n".encode("gbk"))

    result = apply_patch(
        tmp_path,
        {"type": "update", "path": "legacy.txt", "old_string": "旧世界", "new_string": "新世界"},
    )

    assert result.status == "ok"
    assert path.read_bytes() == "你好，新世界\r\n".encode("gbk")
    assert result.output["encoding"] == "gbk"
    assert result.output["newline"] == "crlf"


def test_apply_patch_preserves_crlf_on_update(tmp_path: Path):
    path = tmp_path / "app.py"
    path.write_bytes(b"one\r\ntwo\r\n")

    result = apply_patch(tmp_path, {"type": "update", "path": "app.py", "old_string": "two", "new_string": "three"})

    assert result.status == "ok"
    assert path.read_bytes() == b"one\r\nthree\r\n"
    assert result.output["newline"] == "crlf"


def test_apply_patch_rejects_binary_file_update(tmp_path: Path):
    (tmp_path / "image.bin").write_bytes(b"\x00old\x00")

    result = apply_patch(tmp_path, {"type": "update", "path": "image.bin", "old_string": "old", "new_string": "new"})

    assert result.status == "failed"
    assert "binary" in result.output_summary


class TestApplyPatchUpdate:
    """apply_patch with type="update" — replaces exact string in existing file."""

    def test_replaces_exact_string(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("def substract(a, b):\n    return a - b\n", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "update", "path": "app.py", "old_string": "substract", "new_string": "subtract"})

        assert result.status == "ok"
        assert (tmp_path / "app.py").read_text(encoding="utf-8") == "def subtract(a, b):\n    return a - b\n"
        assert "patch" in result.output
        assert "-def substract" in result.output["patch"]
        assert "+def subtract" in result.output["patch"]

    def test_rejects_missing_old_string(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("content", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "update", "path": "app.py", "old_string": ""})

        assert result.status == "rejected"

    def test_reports_not_found(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("hello world", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "update", "path": "app.py", "old_string": "nope", "new_string": "new"})

        assert result.status == "failed"
        assert "not found" in result.output_summary

    def test_reports_ambiguous_match(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("foo foo", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "update", "path": "app.py", "old_string": "foo", "new_string": "bar"})

        assert result.status == "failed"
        assert "appears 2 times" in result.output_summary

    def test_rejects_outside_workspace(self, tmp_path: Path):
        result = apply_patch(tmp_path, {"type": "update", "path": "../outside.py", "old_string": "x", "new_string": "y"})

        assert result.status == "rejected"
        assert not (tmp_path.parent / "outside.py").exists()

    def test_reports_missing_file(self, tmp_path: Path):
        result = apply_patch(tmp_path, {"type": "update", "path": "nonexistent.py", "old_string": "x", "new_string": "y"})

        assert result.status == "failed"
        assert "file not found" in result.output_summary


class TestApplyPatchAddFile:
    """apply_patch with type="add_file" — creates new file."""

    def test_creates_new_file(self, tmp_path: Path):
        result = apply_patch(tmp_path, {"type": "add_file", "path": "new.py", "content": "def hello():\n    pass\n"})

        assert result.status == "ok"
        assert (tmp_path / "new.py").read_text(encoding="utf-8") == "def hello():\n    pass\n"

    def test_rejects_existing_file(self, tmp_path: Path):
        (tmp_path / "existing.py").write_text("old", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "add_file", "path": "existing.py", "content": "new"})

        assert result.status == "rejected"
        assert "already exists" in result.output_summary

    def test_rejects_missing_content(self, tmp_path: Path):
        result = apply_patch(tmp_path, {"type": "add_file", "path": "new.py"})

        assert result.status == "rejected"

    def test_outside_workspace(self, tmp_path: Path):
        result = apply_patch(tmp_path, {"type": "add_file", "path": "../outside.py", "content": "bad"})

        assert result.status == "rejected"
        assert not (tmp_path.parent / "outside.py").exists()


class TestApplyPatchMove:
    """apply_patch with type="move" — renames file."""

    def test_moves_file(self, tmp_path: Path):
        (tmp_path / "old.py").write_text("content", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "move", "old_path": "old.py", "new_path": "new.py"})

        assert result.status == "ok"
        assert not (tmp_path / "old.py").exists()
        assert (tmp_path / "new.py").read_text(encoding="utf-8") == "content"

    def test_rejects_missing_source(self, tmp_path: Path):
        result = apply_patch(tmp_path, {"type": "move", "old_path": "missing.py", "new_path": "new.py"})

        assert result.status == "failed"

    def test_rejects_existing_destination(self, tmp_path: Path):
        (tmp_path / "src.py").write_text("src", encoding="utf-8")
        (tmp_path / "dst.py").write_text("dst", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "move", "old_path": "src.py", "new_path": "dst.py"})

        assert result.status == "failed"

    def test_outside_workspace(self, tmp_path: Path):
        (tmp_path / "ok.py").write_text("x", encoding="utf-8")
        result = apply_patch(tmp_path, {"type": "move", "old_path": "ok.py", "new_path": "../outside.py"})

        assert result.status == "rejected"


class TestApplyPatchValidation:
    """apply_patch general validation."""

    def test_rejects_invalid_type(self, tmp_path: Path):
        result = apply_patch(tmp_path, {"type": "unknown"})

        assert result.status == "rejected"
        assert "must be one of" in result.output_summary
