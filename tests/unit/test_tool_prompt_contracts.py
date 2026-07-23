from pathlib import Path

from coding_agent.agent import AgentConfig, ToolAgent
from coding_agent.models import BenchmarkTask
from coding_agent.models import ToolName
from coding_agent.tools.schemas import TOOL_SCHEMAS


def test_run_tests_schema_explicitly_rejects_python_scripts_and_shell_commands():
    schema = TOOL_SCHEMAS[ToolName.RUN_TESTS]
    text = " ".join(
        [
            schema["description"],
            schema["parameters"]["targets"]["description"],
            " ".join(schema["examples"]),
        ]
    )

    assert "pytest target" in text
    assert "Do not pass shell commands" in text
    assert "python script.py" in text
    assert "python reproduce_issue.py" in text
    assert "run_python" not in text


def test_read_file_schema_does_not_expose_limit_parameter():
    schema = TOOL_SCHEMAS[ToolName.READ_FILE]
    text = " ".join(
        [
            schema["description"],
            " ".join(schema["parameters"]),
            " ".join(schema["examples"]),
        ]
    )

    assert "limit" not in schema["parameters"]
    assert '"limit"' not in text
    assert "Use offset" in schema["description"]


def test_system_prompt_run_tests_boundary_matches_schema():
    template = Path("src/coding_agent/config/templates/system.j2").read_text(
        encoding="utf-8"
    )

    assert "run_tests: Run pytest only" in template
    assert "Do not pass shell commands" in template
    assert "python script.py" in template
    assert "If you need a diagnostic" in template
    assert "run_python" not in template


def test_system_prompt_requires_official_validation_and_rejects_test_self_proof():
    template = Path("src/coding_agent/config/templates/system.j2").read_text(
        encoding="utf-8"
    )

    assert "benchmark validation is the success criterion" in template
    assert "FAIL_TO_PASS" in template
    assert "Self-written tests are diagnostic only" in template
    assert "Do not modify existing tests, fixtures, snapshots, or expected outputs" in template
    assert "Do not use test changes to prove an implementation is correct" in template


def test_tool_agent_renders_fail_to_pass_targets_in_system_prompt(tmp_path):
    captured = {}

    class CapturingModel:
        model_name = "fake"

        def query(self, messages, tools=None):
            captured["system"] = messages[0]["content"]
            return {"role": "assistant", "content": "done", "extra": {}}

    task = BenchmarkTask(
        instance_id="repo__issue-1",
        workspace=tmp_path,
        problem_statement="Fix it.",
        allowed_test_commands=("test/test_issue.py::test_fix",),
        fail_to_pass=("test/test_issue.py::test_fix",),
    )
    template = Path("src/coding_agent/config/templates/system.j2").read_text(
        encoding="utf-8"
    )
    agent = ToolAgent(
        model=CapturingModel(),
        executor=None,
        config=AgentConfig(
            system_template=template,
            instance_template="{{ problem_statement }}",
            step_limit=1,
        ),
    )

    agent.run(task)

    assert "Official FAIL_TO_PASS targets" in captured["system"]
    assert "test/test_issue.py::test_fix" in captured["system"]
