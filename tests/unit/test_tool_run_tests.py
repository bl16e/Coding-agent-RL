import sys
from pathlib import Path

from coding_agent.tools.run_tests import run_tests


def test_run_tests_executes_allowed_command(tmp_path: Path):
    command = f"{sys.executable} -c \"print('ok')\""

    result = run_tests(tmp_path, {"command": command}, allowed_commands=(command,), timeout_seconds=5)

    assert result.status == "ok"
    assert result.test_result is not None
    assert result.test_result.status.value == "passed"


def test_run_tests_rejects_undeclared_command(tmp_path: Path):
    result = run_tests(tmp_path, {"command": "python -m pytest"}, allowed_commands=(), timeout_seconds=5)

    assert result.status == "rejected"
    assert result.test_result is not None
    assert result.test_result.status.value == "rejected"
    assert result.test_result.output_summary == "command is not allowed"


def test_run_tests_rejects_near_match_command(tmp_path: Path):
    allowed = f"{sys.executable} -m pytest tests/test_issue.py"
    result = run_tests(
        tmp_path,
        {"command": f"{allowed} tests/test_regression.py"},
        allowed_commands=(allowed,),
        timeout_seconds=5,
    )

    assert result.status == "rejected"
    assert result.test_result is not None
    assert result.test_result.command.endswith("tests/test_regression.py")


def test_run_tests_records_timeout(tmp_path: Path):
    command = f"{sys.executable} -c \"import time; time.sleep(1)\""

    result = run_tests(tmp_path, {"command": command}, allowed_commands=(command,), timeout_seconds=0.01)

    assert result.status == "timeout"
    assert result.test_result is not None
    assert result.test_result.status.value == "timeout"
