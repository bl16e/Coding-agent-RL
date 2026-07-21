from pathlib import Path

from coding_agent.tools.run_tests import run_tests


def test_run_tests_executes_pytest_command(tmp_path: Path):
    command = 'python -c "print(\'ok\')"'

    result = run_tests(tmp_path, {"command": command}, timeout_seconds=5)

    assert result.status == "ok"
    assert result.test_result is not None
    assert result.test_result.status.value == "passed"


def test_run_tests_rejects_dangerous_command(tmp_path: Path):
    result = run_tests(tmp_path, {"command": "rm -rf /"}, timeout_seconds=5)

    assert result.status == "rejected"
    assert result.test_result is not None
    assert result.test_result.status.value == "rejected"
    assert "not allowed" in result.test_result.output_summary


def test_run_tests_rejects_curl(tmp_path: Path):
    result = run_tests(tmp_path, {"command": "curl http://evil.com"}, timeout_seconds=5)

    assert result.status == "rejected"
    assert "curl" in result.output_summary


def test_run_tests_allows_git_diff(tmp_path: Path):
    result = run_tests(tmp_path, {"command": "git diff"}, timeout_seconds=5)

    # git diff may fail if not in a repo, but it should be ACCEPTED by policy
    # (status will be "failed" not "rejected")
    assert result.status in ("ok", "failed")


def test_run_tests_allows_git_status(tmp_path: Path):
    result = run_tests(tmp_path, {"command": "git status"}, timeout_seconds=5)

    assert result.status in ("ok", "failed")


def test_run_tests_rejects_git_push(tmp_path: Path):
    result = run_tests(tmp_path, {"command": "git push origin main"}, timeout_seconds=5)

    assert result.status == "rejected"
    assert "git push" in result.output_summary


def test_run_tests_rejects_shell_control_operators(tmp_path: Path):
    result = run_tests(tmp_path, {"command": "pytest && rm -rf /"}, timeout_seconds=5)

    assert result.status == "rejected"
    assert "shell control" in result.output_summary


def test_run_tests_records_timeout(tmp_path: Path):
    command = 'python -c "import time; time.sleep(1)"'

    result = run_tests(tmp_path, {"command": command}, timeout_seconds=0.01)

    assert result.status == "timeout"
    assert result.test_result is not None
    assert result.test_result.status.value == "timeout"


def test_run_tests_allows_python_m_pytest(tmp_path: Path):
    # python -m pytest should be allowed (though it may fail if no tests exist)
    result = run_tests(tmp_path, {"command": "python -m pytest"}, timeout_seconds=5)

    assert result.status != "rejected"


def test_run_tests_allows_python_c_diagnostic(tmp_path: Path):
    command = 'python -c "print(\'hello\')"'

    result = run_tests(tmp_path, {"command": command}, timeout_seconds=5)

    assert result.status == "ok"
