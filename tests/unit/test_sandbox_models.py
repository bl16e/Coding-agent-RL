from coding_agent.models import (
    BaseImage,
    RunBudget,
    RunStatus,
    RunSummary,
    SandboxMetadata,
    TaskSandbox,
    ValidationTestSet,
)


def test_run_summary_serializes_sandbox_metadata():
    base_image = BaseImage(
        repo="django/django",
        image="swebench-django:latest",
        repo_path="/workspace/repo",
        official_compatible=True,
        compatibility_source="official setup notes",
    )
    sandbox = TaskSandbox(
        container_name="coding-agent-django-1",
        base_image=base_image,
        instance_id="django__django-11099",
        repo="django/django",
        base_commit="abc123",
        repo_path="/workspace/repo",
        status="ready",
    )
    validation = ValidationTestSet(
        fail_to_pass=("tests/test_issue.py::test_fix",),
        pass_to_pass=(),
        command_source="registered_template",
        allowed_commands=("python -m pytest tests/test_issue.py::test_fix",),
        include_pass_to_pass=False,
    )
    summary = RunSummary(
        run_id="run-1",
        instance_id="django__django-11099",
        model_name="mock-model",
        status=RunStatus.INCOMPLETE,
        budget=RunBudget(max_steps=1, timeout_seconds=60, test_timeout_seconds=10),
        sandbox=SandboxMetadata(task_sandbox=sandbox, validation_test_set=validation),
    )

    data = summary.to_dict()

    assert data["sandbox"]["task_sandbox"]["base_image"]["official_compatible"] is True
    assert data["sandbox"]["validation_test_set"]["command_source"] == "registered_template"
