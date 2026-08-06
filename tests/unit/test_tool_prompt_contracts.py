from pathlib import Path

from coding_agent.agent import AgentConfig, ToolAgent
from coding_agent.models import BenchmarkTask, ToolName
from coding_agent.tools.schemas import TOOL_SCHEMAS


def test_execute_bash_schema_warns_against_blocked_shell_forms():
    schema = TOOL_SCHEMAS[ToolName.EXECUTE_BASH]
    text = " ".join(
        [
            schema["description"],
            schema["parameters"]["command"]["description"],
            " ".join(schema["examples"]),
        ]
    )

    assert "Pipes are allowed only" in text
    assert "redirection" in text
    assert "cat" in text
    assert "git" in text
    assert "pipe only to head or tail" in text
    assert "except 2>&1" in text


def test_tool_schema_routes_filename_search_through_search():
    search_schema = TOOL_SCHEMAS[ToolName.SEARCH]
    execute_schema = TOOL_SCHEMAS[ToolName.EXECUTE_BASH]
    text = " ".join(
        [
            search_schema["description"],
            " ".join(param.get("description", "") for param in search_schema["parameters"].values()),
            " ".join(search_schema["examples"]),
            execute_schema["description"],
        ]
    )

    assert "filename/path search" in text
    assert "search_code" not in text
    assert 'match_type="path"' in text
    assert 'match_type="content"' in text


def test_system_prompt_warns_against_blocked_shell_forms():
    template = Path("src/coding_agent/config/templates/system.j2").read_text(
        encoding="utf-8"
    )

    assert "Pipes are allowed only" in template
    assert "redirection" in template
    assert "cat" in template
    assert "git" in template
    assert "pipe only to head or tail" in template
    assert "except 2>&1" in template


def test_system_prompt_includes_tool_substitution_rules():
    template = Path("src/coding_agent/config/templates/system.j2").read_text(
        encoding="utf-8"
    )

    assert "Tool substitution rules" in template
    assert "To find files by filename" in template
    assert 'match_type="path"' in template
    assert "search_code" not in template
    assert "Do not use git status/log/show/diff" in template


def test_system_prompt_requires_finish_after_fix_and_diagnostic_validation():
    template = Path("src/coding_agent/config/templates/system.j2").read_text(
        encoding="utf-8"
    )

    assert "Call finish" in template
    assert "benchmark validation is the success criterion" in template
    assert "Self-written tests are diagnostic only" in template
    assert "Do not modify existing tests" in template
    assert "Do not add new tests to the repository patch" in template


def test_system_prompt_requires_brief_intent_before_tool_calls():
    template = Path("src/coding_agent/config/templates/system.j2").read_text(
        encoding="utf-8"
    )

    assert "brief intent" in template
    assert "before every tool call" in template


def test_tool_agent_renders_problem_statement_in_system_prompt(tmp_path):
    captured = {}

    class CapturingModel:
        model_name = "fake"

        def query(self, messages, tools=None):
            captured["system"] = messages[0]["content"]
            return {"role": "assistant", "content": "done", "extra": {}}

    task = BenchmarkTask(
        instance_id="repo__issue-1",
        workspace=tmp_path,
        problem_statement="Fix the pyarrow indexing bug.",
        allowed_test_commands=("python -m pytest test_issue.py",),
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

    assert "Fix the pyarrow indexing bug." in captured["system"]
