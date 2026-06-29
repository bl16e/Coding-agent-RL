"""Unit tests for SWE-Bench Base/Env/Instance image graph planning."""

import pytest

from coding_agent.models import AdaptedTestSpec
from tests.unit.fakes.test_swebench_runtime_fakes import FakeOfficialRuntimeDocker

from coding_agent.swebench.images import (
    MissingRuntimeImagesError,
    build_missing_images,
    inspect_image_graph,
    plan_image_graph,
)


def _testspec(**overrides) -> AdaptedTestSpec:
    values = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "version": "3.0",
        "base_commit": "abc123",
        "repo_path": "/testbed",
        "env_name": "testbed",
        "fail_to_pass": ("tests/test_issue.py::test_fix",),
        "repo_script": "repo setup",
        "env_script": "env setup",
        "eval_script": "python -m pytest {tests}",
        "language": "py",
        "arch": "x86_64",
        "platform": "linux/x86_64",
        "base_image_key": "sweb.base.py.x86_64:latest",
        "env_image_key": "sweb.env.py.x86_64.hash:latest",
        "instance_image_key": "sweb.eval.x86_64.django__django-11099:latest",
        "repo_version_source": "SWE-bench/swebench/harness/constants/python.py",
    }
    values.update(overrides)
    return AdaptedTestSpec(**values)


def test_image_graph_records_reuse_and_missing_layers_in_order():
    plan = plan_image_graph(
        _testspec(),
        existing_images={"sweb.base.py.x86_64:latest"},
        build_missing=True,
    )

    assert plan.ordered_image_keys == (
        "sweb.base.py.x86_64:latest",
        "sweb.env.py.x86_64.hash:latest",
        "sweb.eval.x86_64.django__django-11099:latest",
    )
    assert plan.reused_images == ("sweb.base.py.x86_64:latest",)
    assert plan.missing_images == (
        "sweb.env.py.x86_64.hash:latest",
        "sweb.eval.x86_64.django__django-11099:latest",
    )


def test_image_graph_rejects_missing_layers_without_opt_in_build():
    with pytest.raises(MissingRuntimeImagesError, match="sweb.env"):
        plan_image_graph(_testspec(), existing_images={"sweb.base.py.x86_64:latest"}, build_missing=False)


def test_inspect_image_graph_uses_docker_image_exists():
    docker = FakeOfficialRuntimeDocker(present_images={"sweb.base.py.x86_64:latest"})

    plan = inspect_image_graph(_testspec(), docker=docker, build_missing=True)

    assert plan.reused_images == ("sweb.base.py.x86_64:latest",)
    assert ("image_exists", ("sweb.env.py.x86_64.hash:latest",)) in docker.calls


def test_build_missing_images_runs_base_env_instance_order():
    docker = FakeOfficialRuntimeDocker()
    plan = plan_image_graph(_testspec(), existing_images=set(), build_missing=True)

    built = build_missing_images(_testspec(), docker=docker, plan=plan)

    assert built == (
        "sweb.base.py.x86_64:latest",
        "sweb.env.py.x86_64.hash:latest",
        "sweb.eval.x86_64.django__django-11099:latest",
    )
    assert [call[0] for call in docker.calls] == ["build_image", "build_image", "build_image"]


def test_build_missing_images_uses_testspec_scripts_in_dockerfiles():
    docker = FakeOfficialRuntimeDocker()
    plan = plan_image_graph(_testspec(), existing_images=set(), build_missing=True)

    build_missing_images(
        _testspec(
            repo_script="git clone repo",
            env_script="conda create -n testbed python=3.11 -y",
            eval_script="echo eval",
        ),
        docker=docker,
        plan=plan,
    )

    dockerfiles = {call[1][0]: call[1][1] for call in docker.calls if call[0] == "build_image"}
    assert "FROM ubuntu" in dockerfiles["sweb.base.py.x86_64:latest"]
    assert "conda create -n testbed python=3.11 -y" in dockerfiles["sweb.env.py.x86_64.hash:latest"]
    assert "git clone repo" in dockerfiles["sweb.eval.x86_64.django__django-11099:latest"]
    assert "echo eval" in dockerfiles["sweb.eval.x86_64.django__django-11099:latest"]
