from pathlib import Path

from coding_agent.models import Outcome, ToolName
from coding_agent.tools.executor import LocalToolExecutor


def test_local_tool_executor_preserves_read_file_behavior(tmp_path: Path):
    (tmp_path / "README.md").write_bytes(b"hello\n")
    executor = LocalToolExecutor(
        workspace=tmp_path,
        test_timeout_seconds=10,
    )

    result = executor.execute(ToolName.READ_FILE, {"file_path": "README.md"})

    assert result.status is Outcome.OK
    assert result.output["content"] == "   1\thello\n"
    assert result.output["encoding"] == "utf-8"
    assert result.output["newline"] == "lf"


def test_local_tool_executor_rejects_dangerous_test_command(tmp_path: Path):
    executor = LocalToolExecutor(
        workspace=tmp_path,
        test_timeout_seconds=10,
    )

    result = executor.execute(ToolName.RUN_TESTS, {"command": "rm -rf /"})

    assert result.status is Outcome.REJECTED
    assert "not allowed" in result.output_summary


def test_local_tool_executor_allows_pytest(tmp_path: Path):
    executor = LocalToolExecutor(
        workspace=tmp_path,
        test_timeout_seconds=10,
    )

    result = executor.execute(ToolName.RUN_TESTS, {"command": "pytest"})

    # May fail (no tests) but should not be rejected
    assert result.status != Outcome.REJECTED
