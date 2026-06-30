import pytest

from coding_agent.tools.test_command_policy import validate_self_test_command


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/test_issue.py",
        "python -m pytest tests/test_issue.py -q",
        "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1 test_utils.tests",
        "python -c \"print('diagnostic')\"",
        "python test_newline_fix.py",
        "python scripts/check_issue.py --flag",
    ],
)
def test_self_test_policy_allows_test_and_diagnostic_commands(command):
    assert validate_self_test_command(command).allowed is True


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/test_issue.py && rm -rf /tmp/x",
        "python -m pytest tests/test_issue.py; git status",
        "python -c \"print('x')\" | tee out.txt",
        "git checkout abc tests/test_issue.py",
        "git apply -v -",
        "git reset --hard",
        "rm -rf django",
        "pip install requests",
        "python -m pip install requests",
        "apt install curl",
        "curl https://example.com",
        "wget https://example.com/file",
        "docker ps",
        "python ../outside.py",
        "/usr/bin/python test.py",
    ],
)
def test_self_test_policy_rejects_mutating_or_shell_commands(command):
    result = validate_self_test_command(command)
    assert result.allowed is False
    assert result.reason
