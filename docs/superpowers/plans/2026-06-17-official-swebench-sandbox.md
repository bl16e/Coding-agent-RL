# Official SWE-Bench Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an official-style SWE-Bench environment preparation pipeline while preserving host-orchestrated agent solving with tools executing inside Docker containers.

**Architecture:** Add an internal adapted TestSpec layer, official-style base/env/instance image resolution and build orchestration, and official-style eval metadata. Keep Docker behind `sandbox/` modules and keep the agent loop independent of Docker and SWE-Bench image details.

**Tech Stack:** Python 3.11+, pytest, argparse, Docker CLI wrapper, existing `coding_agent` dataclasses and SWE-Bench dataset loader.

---

## File Structure

- Create `src/coding_agent/swebench/testspec.py`: adapted TestSpec dataclass, image key calculation, task-record conversion.
- Create `src/coding_agent/swebench/repo_specs.py`: internal repo/version metadata needed by adapted TestSpec. Start with compact fixtures used by tests, then add real supported entries incrementally.
- Create `src/coding_agent/swebench/script_builders.py`: official-style env, repo, and eval script generation.
- Create `src/coding_agent/swebench/images.py`: image existence checks, build plan creation, build execution order.
- Create `src/coding_agent/swebench/grading.py`: parse official-style eval output into resolved status.
- Modify `src/coding_agent/models.py`: add image graph metadata without breaking existing artifacts.
- Modify `src/coding_agent/sandbox/docker_cli.py`: add `build_image()` and image-key friendly helpers.
- Modify `src/coding_agent/sandbox/manager.py`: prepare containers from instance images.
- Modify `src/coding_agent/sandbox/tools.py`: add temporary `test_patch` handling for `run_tests`.
- Modify `src/coding_agent/swebench/validation.py`: make validation derive from adapted TestSpec, not registry command templates.
- Modify `src/coding_agent/swebench/sandbox_run.py`: route prepare/run through adapted TestSpec image graph.
- Modify `src/coding_agent/cli.py`: add `prepare-images`, rename official-style prepare/run surfaces, add `--build-missing`.
- Test files:
  - Create `tests/unit/test_swebench_testspec.py`
  - Create `tests/unit/test_swebench_script_builders.py`
  - Create `tests/unit/test_swebench_repo_specs.py`
  - Create `tests/unit/test_swebench_images.py`
  - Create `tests/unit/test_swebench_grading.py`
  - Modify `tests/unit/test_docker_cli.py`
  - Modify `tests/unit/test_sandbox_manager.py`
  - Modify `tests/unit/test_container_tools.py`
  - Modify `tests/unit/test_swebench_validation.py`
  - Modify `tests/integration/test_swebench_sandbox_run.py`
  - Modify `tests/contract/test_cli_swebench_run_contract.py`
  - Create `tests/contract/test_cli_swebench_prepare_images_contract.py`

## Task 1: Adapted TestSpec Domain Object

**Files:**
- Create: `src/coding_agent/swebench/testspec.py`
- Create: `tests/unit/test_swebench_testspec.py`
- Modify: `src/coding_agent/swebench/__init__.py`

- [ ] **Step 1: Write the failing test**

Add `tests/unit/test_swebench_testspec.py`:

```python
from coding_agent.swebench.dataset import SwebenchTaskRecord
from coding_agent.swebench.testspec import make_test_spec


def _record() -> SwebenchTaskRecord:
    return SwebenchTaskRecord(
        instance_id="django__django-12345",
        repo="django/django",
        version="4.2",
        base_commit="abc123",
        problem_statement="Fix issue",
        test_patch="diff --git a/tests/test_issue.py b/tests/test_issue.py\n",
        fail_to_pass=("tests.test_issue.TestIssue.test_fix",),
        pass_to_pass=("tests.test_existing.TestExisting.test_ok",),
        environment_setup_commit=None,
        eval_script=None,
    )


def test_make_test_spec_derives_official_style_image_keys():
    spec = make_test_spec(_record(), arch="x86_64")

    assert spec.instance_id == "django__django-12345"
    assert spec.repo_path == "/testbed"
    assert spec.env_name == "testbed"
    assert spec.platform == "linux/x86_64"
    assert spec.base_image_key == "sweb.base.py.x86_64:latest"
    assert spec.env_image_key.startswith("sweb.env.py.x86_64.")
    assert spec.env_image_key.endswith(":latest")
    assert spec.instance_image_key == "sweb.eval.x86_64.django_django-12345:latest"
    assert spec.fail_to_pass == ("tests.test_issue.TestIssue.test_fix",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_swebench_testspec.py::test_make_test_spec_derives_official_style_image_keys -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swebench.testspec'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/coding_agent/swebench/testspec.py`:

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from coding_agent.swebench.dataset import SwebenchTaskRecord


LATEST = "latest"
MAP_REPO_TO_LANGUAGE = {"django/django": "py"}


@dataclass(frozen=True)
class SwebenchTestSpec:
    instance_id: str
    repo: str
    version: str
    base_commit: str
    repo_path: str
    env_name: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    test_patch: str
    repo_script: str
    env_script: str
    eval_script: str
    arch: str
    language: str
    base_image_tag: str = LATEST
    env_image_tag: str = LATEST
    instance_image_tag: str = LATEST

    @property
    def platform(self) -> str:
        if self.arch == "x86_64":
            return "linux/x86_64"
        if self.arch == "arm64":
            return "linux/arm64/v8"
        raise ValueError(f"unsupported architecture: {self.arch}")

    @property
    def base_image_key(self) -> str:
        return f"sweb.base.{self.language}.{self.arch}:{self.base_image_tag}"

    @property
    def env_image_key(self) -> str:
        digest = hashlib.sha256(self.env_script.encode("utf-8")).hexdigest()[:22]
        return f"sweb.env.{self.language}.{self.arch}.{digest}:{self.env_image_tag}"

    @property
    def instance_image_key(self) -> str:
        safe = re.sub(r"__+", "_", self.instance_id.lower())
        return f"sweb.eval.{self.arch}.{safe}:{self.instance_image_tag}"


def make_test_spec(record: SwebenchTaskRecord, *, arch: str = "x86_64") -> SwebenchTestSpec:
    language = MAP_REPO_TO_LANGUAGE[record.repo]
    env_script = f"echo setup env for {record.repo} {record.version}"
    repo_script = f"git reset --hard {record.base_commit}"
    eval_script = record.eval_script or "echo eval"
    return SwebenchTestSpec(
        instance_id=record.instance_id,
        repo=record.repo,
        version=record.version,
        base_commit=record.base_commit,
        repo_path="/testbed",
        env_name="testbed",
        fail_to_pass=tuple(record.fail_to_pass),
        pass_to_pass=tuple(record.pass_to_pass),
        test_patch=record.test_patch,
        repo_script=repo_script,
        env_script=env_script,
        eval_script=eval_script,
        arch=arch,
        language=language,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_swebench_testspec.py::test_make_test_spec_derives_official_style_image_keys -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swebench/testspec.py tests/unit/test_swebench_testspec.py src/coding_agent/swebench/__init__.py
git commit -m "feat: add adapted swebench testspec"
```

## Task 2: Repo Metadata And Official-Style Script Builders

**Files:**
- Create: `src/coding_agent/swebench/repo_specs.py`
- Create: `src/coding_agent/swebench/script_builders.py`
- Modify: `src/coding_agent/swebench/testspec.py`
- Create: `tests/unit/test_swebench_script_builders.py`
- Modify: `tests/unit/test_swebench_testspec.py`

- [ ] **Step 1: Write the failing tests**

Add `tests/unit/test_swebench_script_builders.py`:

```python
from coding_agent.swebench.script_builders import make_eval_script, make_repo_script


TEST_PATCH = """diff --git a/tests/test_issue.py b/tests/test_issue.py
--- a/tests/test_issue.py
+++ b/tests/test_issue.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test_new.py b/tests/test_new.py
--- /dev/null
+++ b/tests/test_new.py
@@ -0,0 +1 @@
+new test
"""


def test_eval_script_applies_test_patch_between_reset_commands():
    script = make_eval_script(
        repo_path="/testbed",
        base_commit="abc123",
        test_patch=TEST_PATCH,
        test_command="python -m pytest",
        test_directives=("tests/test_issue.py::test_fix",),
    )

    assert "git checkout abc123 tests/test_issue.py" in script
    assert "rm -f tests/test_new.py" in script
    assert "git apply -v - <<'EOF_114329324912'" in script
    assert ">>>>> Start Test Output" in script
    assert "python -m pytest tests/test_issue.py::test_fix" in script
    assert ">>>>> End Test Output" in script
    assert script.count("git checkout abc123 tests/test_issue.py") == 2


def test_repo_script_removes_remote_and_prepares_clean_baseline():
    script = make_repo_script(
        repo="django/django",
        repo_path="/testbed",
        base_commit="abc123",
        install_commands=("python -m pip install -e .",),
    )

    assert "git clone -o origin https://github.com/django/django /testbed" in script
    assert "git reset --hard abc123" in script
    assert "git remote remove origin" in script
    assert "git commit --allow-empty -am SWE-bench" in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_swebench_script_builders.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swebench.script_builders'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/coding_agent/swebench/script_builders.py`:

```python
from __future__ import annotations

from unidiff import PatchSet

START_TEST_OUTPUT = ">>>>> Start Test Output"
END_TEST_OUTPUT = ">>>>> End Test Output"
TEST_PATCH_DELIMITER = "EOF_114329324912"


def _modified_files(patch: str) -> tuple[str, ...]:
    files: list[str] = []
    for file_patch in PatchSet(patch):
        if file_patch.source_file != "/dev/null" and file_patch.source_file.startswith("a/"):
            files.append(file_patch.source_file[2:])
    return tuple(files)


def _new_files(patch: str) -> tuple[str, ...]:
    files: list[str] = []
    for file_patch in PatchSet(patch):
        if file_patch.source_file == "/dev/null":
            target = file_patch.target_file[2:] if file_patch.target_file.startswith("b/") else file_patch.target_file
            files.append(target)
    return tuple(files)


def make_repo_script(*, repo: str, repo_path: str, base_commit: str, install_commands: tuple[str, ...]) -> str:
    commands = [
        "#!/bin/bash",
        "set -euxo pipefail",
        f"git clone -o origin https://github.com/{repo} {repo_path}",
        f"chmod -R 777 {repo_path}",
        f"cd {repo_path}",
        f"git reset --hard {base_commit}",
        "git remote remove origin",
        *install_commands,
        "git config --global user.email setup@swebench.config",
        "git config --global user.name SWE-bench",
        "git commit --allow-empty -am SWE-bench",
    ]
    return "\n".join(commands) + "\n"


def make_env_script(*, env_name: str, python_version: str, packages: str, pip_packages: tuple[str, ...]) -> str:
    commands = [
        "#!/bin/bash",
        "set -euxo pipefail",
        "source /opt/miniconda3/bin/activate",
        f"conda create -n {env_name} python={python_version} {packages} -y",
        f"conda activate {env_name}",
    ]
    if pip_packages:
        commands.append("python -m pip install " + " ".join(pip_packages))
    return "\n".join(commands) + "\n"


def make_eval_script(
    *,
    repo_path: str,
    base_commit: str,
    test_patch: str,
    test_command: str,
    test_directives: tuple[str, ...],
) -> str:
    reset_commands: list[str] = []
    modified = _modified_files(test_patch)
    new = _new_files(test_patch)
    if modified:
        reset_commands.append(f"git checkout {base_commit} {' '.join(modified)}")
    if new:
        reset_commands.append(f"rm -f {' '.join(new)}")
    apply_patch = f"git apply -v - <<'{TEST_PATCH_DELIMITER}'\n{test_patch}\n{TEST_PATCH_DELIMITER}"
    full_test_command = " ".join((test_command, *test_directives)).strip()
    commands = [
        "#!/bin/bash",
        "set -uxo pipefail",
        "source /opt/miniconda3/bin/activate",
        "conda activate testbed",
        f"cd {repo_path}",
        f"git config --global --add safe.directory {repo_path}",
        *reset_commands,
        apply_patch,
        f": '{START_TEST_OUTPUT}'",
        full_test_command,
        f": '{END_TEST_OUTPUT}'",
        *reset_commands,
    ]
    return "\n".join(commands) + "\n"
```

Create `src/coding_agent/swebench/repo_specs.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoVersionSpec:
    language: str
    python_version: str
    packages: str
    install_commands: tuple[str, ...]
    pip_packages: tuple[str, ...]
    test_command: str


REPO_VERSION_SPECS: dict[str, dict[str, RepoVersionSpec]] = {
    "django/django": {
        "4.2": RepoVersionSpec(
            language="py",
            python_version="3.11",
            packages="pytest",
            install_commands=("python -m pip install -e .",),
            pip_packages=(),
            test_command="python -m pytest",
        )
    }
}
```

Update `make_test_spec()` in `src/coding_agent/swebench/testspec.py` to read `RepoVersionSpec` and call the builders.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_swebench_script_builders.py tests/unit/test_swebench_testspec.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swebench/repo_specs.py src/coding_agent/swebench/script_builders.py src/coding_agent/swebench/testspec.py tests/unit/test_swebench_script_builders.py tests/unit/test_swebench_testspec.py
git commit -m "feat: generate official style swebench scripts"
```

## Task 3: Supported Repo Metadata Coverage

**Files:**
- Modify: `src/coding_agent/swebench/repo_specs.py`
- Create: `tests/unit/test_swebench_repo_specs.py`

- [ ] **Step 1: Write the failing tests**

Add `tests/unit/test_swebench_repo_specs.py`:

```python
import pytest

from coding_agent.swebench.repo_specs import REPO_VERSION_SPECS, get_repo_version_spec


@pytest.mark.parametrize(
    ("repo", "version"),
    [
        ("django/django", "4.2"),
        ("pytest-dev/pytest", "7.4"),
        ("sympy/sympy", "1.12"),
        ("scikit-learn/scikit-learn", "1.3"),
    ],
)
def test_core_lite_python_repos_have_repo_version_specs(repo, version):
    spec = get_repo_version_spec(repo, version)

    assert spec.language == "py"
    assert spec.test_command
    assert spec.install_commands


def test_unknown_repo_version_reports_supported_key():
    with pytest.raises(KeyError, match="unsupported SWE-Bench repo/version: missing/repo@0.1"):
        get_repo_version_spec("missing/repo", "0.1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_swebench_repo_specs.py -q`

Expected: FAIL because `get_repo_version_spec` does not exist and the additional repo/version entries are not present.

- [ ] **Step 3: Write minimal implementation**

Add `get_repo_version_spec()` and populate the tested entries in `src/coding_agent/swebench/repo_specs.py`:

```python
def get_repo_version_spec(repo: str, version: str) -> RepoVersionSpec:
    try:
        return REPO_VERSION_SPECS[repo][version]
    except KeyError as exc:
        raise KeyError(f"unsupported SWE-Bench repo/version: {repo}@{version}") from exc
```

Extend `REPO_VERSION_SPECS` with the tested entries using the same field shape as the existing Django entry. Use the local official harness files only as a reference source for command values; do not import them from production code.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_swebench_repo_specs.py tests/unit/test_swebench_testspec.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swebench/repo_specs.py tests/unit/test_swebench_repo_specs.py tests/unit/test_swebench_testspec.py
git commit -m "feat: add swebench repo version metadata"
```

## Task 4: Docker Image Build Planning

**Files:**
- Create: `src/coding_agent/swebench/images.py`
- Create: `tests/unit/test_swebench_images.py`
- Modify: `src/coding_agent/sandbox/docker_cli.py`
- Modify: `tests/unit/test_docker_cli.py`

- [ ] **Step 1: Write the failing tests**

Add `tests/unit/test_swebench_images.py`:

```python
import pytest

from coding_agent.swebench.images import ImageBuildError, ensure_test_spec_images
from coding_agent.swebench.testspec import make_test_spec
from tests.unit.test_swebench_testspec import _record


class FakeDocker:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.builds = []

    def image_exists(self, image):
        return image in self.existing

    def build_image(self, *, image, dockerfile, context_files, platform):
        self.builds.append((image, dockerfile, context_files, platform))
        self.existing.add(image)


def test_missing_images_fail_without_build_missing():
    spec = make_test_spec(_record())

    with pytest.raises(ImageBuildError, match="missing image"):
        ensure_test_spec_images(spec, docker=FakeDocker(), build_missing=False)


def test_build_missing_builds_base_env_instance_in_order():
    spec = make_test_spec(_record())
    docker = FakeDocker()

    result = ensure_test_spec_images(spec, docker=docker, build_missing=True)

    assert result.built_images == (spec.base_image_key, spec.env_image_key, spec.instance_image_key)
    assert [item[0] for item in docker.builds] == [spec.base_image_key, spec.env_image_key, spec.instance_image_key]
    assert docker.builds[1][2]["setup_env.sh"] == spec.env_script
    assert docker.builds[2][2]["setup_repo.sh"] == spec.repo_script
```

Modify `tests/unit/test_docker_cli.py` with:

```python
def test_build_image_uses_docker_build_with_dockerfile_and_context(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, stdout=b"built", stderr=b"")

    docker = DockerCli(runner=runner)
    docker.build_image(
        image="sweb.env.py.x86_64.hash:latest",
        dockerfile="FROM ubuntu:22.04\n",
        context_files={"setup_env.sh": "echo hi\n"},
        platform="linux/x86_64",
        context_dir=tmp_path,
    )

    assert calls[-1][0][:4] == ["docker", "build", "--platform", "linux/x86_64"]
    assert (tmp_path / "Dockerfile").read_text(encoding="utf-8") == "FROM ubuntu:22.04\n"
    assert (tmp_path / "setup_env.sh").read_text(encoding="utf-8") == "echo hi\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_swebench_images.py tests/unit/test_docker_cli.py::test_build_image_uses_docker_build_with_dockerfile_and_context -q`

Expected: FAIL because `coding_agent.swebench.images` and `DockerCli.build_image` do not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/coding_agent/swebench/images.py` with `ImageBuildResult`, `ImageBuildError`, generated Dockerfiles, and `ensure_test_spec_images()`. Add `DockerCli.build_image()` that writes a controlled context directory and runs:

```python
["build", "--platform", platform, "-t", image, str(context_dir)]
```

Use these Dockerfile templates first:

```python
BASE_DOCKERFILE_PY = "FROM --platform={platform} ubuntu:22.04\nRUN apt-get update && apt-get install -y git python3 python3-pip curl wget\n"
ENV_DOCKERFILE_PY = "FROM --platform={platform} {base_image}\nCOPY ./setup_env.sh /root/setup_env.sh\nRUN /bin/bash /root/setup_env.sh\nWORKDIR /testbed\n"
INSTANCE_DOCKERFILE_PY = "FROM --platform={platform} {env_image}\nCOPY ./setup_repo.sh /root/setup_repo.sh\nRUN /bin/bash /root/setup_repo.sh\nWORKDIR /testbed\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_swebench_images.py tests/unit/test_docker_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swebench/images.py src/coding_agent/sandbox/docker_cli.py tests/unit/test_swebench_images.py tests/unit/test_docker_cli.py
git commit -m "feat: build official style swebench images"
```

## Task 5: Prepare Containers From Instance Images

**Files:**
- Modify: `src/coding_agent/models.py`
- Modify: `src/coding_agent/sandbox/manager.py`
- Modify: `tests/unit/test_sandbox_manager.py`
- Modify: `tests/unit/test_sandbox_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_sandbox_manager.py`:

```python
from coding_agent.sandbox.manager import TaskSandboxManager
from coding_agent.swebench.testspec import make_test_spec
from tests.unit.test_swebench_testspec import _record


class RecordingDocker:
    def __init__(self):
        self.calls = []

    def create_container(self, *, name, image):
        self.calls.append(("create", name, image))

    def start_container(self, name):
        self.calls.append(("start", name))

    def exec(self, container, command, **kwargs):
        self.calls.append(("exec", container, tuple(command)))
        if command[-1] == "HEAD":
            return DockerResult(stdout="abc123\n", stderr="", returncode=0)
        return DockerResult(stdout="", stderr="", returncode=0)


def test_prepare_from_testspec_uses_instance_image_not_repo_base():
    spec = make_test_spec(_record())
    docker = RecordingDocker()
    sandbox = TaskSandboxManager(docker=docker).prepare_from_test_spec(spec, run_id="run1")

    assert docker.calls[0] == ("create", sandbox.container_name, spec.instance_image_key)
    assert sandbox.repo_path == "/testbed"
    assert sandbox.image_keys.instance == spec.instance_image_key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_sandbox_manager.py::test_prepare_from_testspec_uses_instance_image_not_repo_base -q`

Expected: FAIL because `prepare_from_test_spec` and `image_keys` do not exist.

- [ ] **Step 3: Write minimal implementation**

Add to `src/coding_agent/models.py`:

```python
@dataclass(frozen=True)
class SwebenchImageKeys:
    base: str
    env: str
    instance: str
```

Add `image_keys: SwebenchImageKeys | None = None` to `TaskSandbox`, keeping `base_image` for legacy compatibility.

Add `TaskSandboxManager.prepare_from_test_spec(spec, run_id=None)`:

```python
def prepare_from_test_spec(self, spec: SwebenchTestSpec, run_id: str | None = None) -> TaskSandbox:
    name = _container_name(spec.instance_id, run_id=run_id)
    self._docker.create_container(name=name, image=spec.instance_image_key)
    self._docker.start_container(name)
    self._docker.exec(name, ["git", "-C", spec.repo_path, "rev-parse", "--is-inside-work-tree"])
    self._docker.exec(name, ["git", "-C", spec.repo_path, "diff", "--quiet"])
    return TaskSandbox(
        container_name=name,
        base_image=BaseImage(repo=spec.repo, image=spec.instance_image_key, repo_path=spec.repo_path, official_compatible=True),
        image_keys=SwebenchImageKeys(base=spec.base_image_key, env=spec.env_image_key, instance=spec.instance_image_key),
        instance_id=spec.instance_id,
        repo=spec.repo,
        base_commit=spec.base_commit,
        repo_path=spec.repo_path,
        status="ready",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_sandbox_manager.py tests/unit/test_sandbox_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/models.py src/coding_agent/sandbox/manager.py tests/unit/test_sandbox_manager.py tests/unit/test_sandbox_models.py
git commit -m "feat: prepare sandboxes from instance images"
```

## Task 6: Official-Style Validation Metadata

**Files:**
- Modify: `src/coding_agent/models.py`
- Modify: `src/coding_agent/swebench/validation.py`
- Modify: `tests/unit/test_swebench_validation.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_swebench_validation.py`:

```python
from coding_agent.swebench.testspec import make_test_spec
from coding_agent.swebench.validation import validation_from_test_spec
from tests.unit.test_swebench_testspec import _record


def test_validation_from_testspec_uses_eval_script_and_fail_to_pass():
    spec = make_test_spec(_record())

    validation = validation_from_test_spec(spec)

    assert validation.command_source == "official_testspec"
    assert validation.eval_script == spec.eval_script
    assert validation.fail_to_pass == spec.fail_to_pass
    assert validation.pass_to_pass == ()
    assert validation.allowed_commands


def test_validation_from_testspec_includes_pass_to_pass_only_when_enabled():
    spec = make_test_spec(_record())

    validation = validation_from_test_spec(spec, include_pass_to_pass=True)

    assert validation.pass_to_pass == spec.pass_to_pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_swebench_validation.py::test_validation_from_testspec_uses_eval_script_and_fail_to_pass tests/unit/test_swebench_validation.py::test_validation_from_testspec_includes_pass_to_pass_only_when_enabled -q`

Expected: FAIL because `validation_from_test_spec` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add `validation_from_test_spec(spec, include_pass_to_pass=False)`:

```python
def validation_from_test_spec(spec: SwebenchTestSpec, *, include_pass_to_pass: bool = False) -> ValidationTestSet:
    pass_to_pass = spec.pass_to_pass if include_pass_to_pass else ()
    selected = spec.fail_to_pass + pass_to_pass
    command = _extract_test_command(spec.eval_script)
    return ValidationTestSet(
        fail_to_pass=spec.fail_to_pass,
        pass_to_pass=pass_to_pass,
        command_source="official_testspec",
        eval_script=spec.eval_script,
        allowed_commands=(command,),
        include_pass_to_pass=include_pass_to_pass,
    )
```

Implement `_extract_test_command()` conservatively by returning the command line between the start and end output markers that is not a shell marker. Keep legacy `build_validation_test_set()` unchanged for compatibility.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_swebench_validation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/models.py src/coding_agent/swebench/validation.py tests/unit/test_swebench_validation.py
git commit -m "feat: derive validation from adapted testspec"
```

## Task 7: Temporary Test Patch Handling In Container Tests

**Files:**
- Modify: `src/coding_agent/sandbox/tools.py`
- Modify: `tests/unit/test_container_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_container_tools.py`:

```python
def test_run_tests_temporarily_applies_test_patch_and_cleans_up():
    docker = FakeDocker()
    executor = ContainerToolExecutor(
        docker=docker,
        container_name="c1",
        repo_path="/testbed",
        allowed_test_commands=("python -m pytest tests/test_issue.py::test_fix",),
        test_timeout_seconds=30,
        test_patch="diff --git a/tests/test_issue.py b/tests/test_issue.py\n",
        test_patch_reset_commands=("git checkout abc123 tests/test_issue.py",),
    )

    result = executor.run_tests("python -m pytest tests/test_issue.py::test_fix")

    commands = [call.command for call in docker.exec_calls]
    assert ["sh", "-lc", "tr -d '\\r' | git -C /testbed apply --whitespace=nowarn -"] in commands
    assert ["sh", "-lc", "cd /testbed && python -m pytest tests/test_issue.py::test_fix"] in commands
    assert ["sh", "-lc", "cd /testbed && git checkout abc123 tests/test_issue.py"] in commands
    assert result.status.value in {"passed", "failed", "execution_error", "timeout"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_container_tools.py::test_run_tests_temporarily_applies_test_patch_and_cleans_up -q`

Expected: FAIL because `ContainerToolExecutor` does not accept `test_patch`.

- [ ] **Step 3: Write minimal implementation**

Add optional constructor fields to `ContainerToolExecutor`:

```python
test_patch: str | None = None
test_patch_reset_commands: tuple[str, ...] = ()
```

Wrap allowed test execution:

```python
if self._test_patch:
    self._docker.exec(self._container_name, ["sh", "-lc", f"tr -d '\\r' | git -C {self._repo_path} apply --whitespace=nowarn -"], stdin=self._test_patch)
try:
    result = self._docker.exec(self._container_name, ["sh", "-lc", f"cd {self._repo_path} && {command}"], timeout_seconds=self._test_timeout_seconds)
finally:
    for reset in self._test_patch_reset_commands:
        self._docker.exec(self._container_name, ["sh", "-lc", f"cd {self._repo_path} && {reset}"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_container_tools.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/sandbox/tools.py tests/unit/test_container_tools.py
git commit -m "feat: run tests with temporary swebench test patch"
```

## Task 8: Official-Style Final Eval And Grading

**Files:**
- Create: `src/coding_agent/swebench/grading.py`
- Create: `tests/unit/test_swebench_grading.py`
- Modify: `src/coding_agent/swebench/sandbox_run.py`

- [ ] **Step 1: Write the failing tests**

Add `tests/unit/test_swebench_grading.py`:

```python
from coding_agent.swebench.grading import grade_eval_output


def test_grade_eval_output_resolves_when_fail_to_pass_passes():
    output = """
>>>>> Start Test Output
tests/test_issue.py::test_fix PASSED
>>>>> End Test Output
"""

    report = grade_eval_output(
        output,
        fail_to_pass=("tests/test_issue.py::test_fix",),
        pass_to_pass=(),
    )

    assert report.resolved is True
    assert report.fail_to_pass_success == ("tests/test_issue.py::test_fix",)


def test_grade_eval_output_requires_pass_to_pass_when_provided():
    output = """
>>>>> Start Test Output
tests/test_issue.py::test_fix PASSED
tests/test_existing.py::test_ok FAILED
>>>>> End Test Output
"""

    report = grade_eval_output(
        output,
        fail_to_pass=("tests/test_issue.py::test_fix",),
        pass_to_pass=("tests/test_existing.py::test_ok",),
    )

    assert report.resolved is False
    assert report.pass_to_pass_failure == ("tests/test_existing.py::test_ok",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_swebench_grading.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_agent.swebench.grading'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/coding_agent/swebench/grading.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

START = ">>>>> Start Test Output"
END = ">>>>> End Test Output"


@dataclass(frozen=True)
class EvalReport:
    resolved: bool
    fail_to_pass_success: tuple[str, ...]
    fail_to_pass_failure: tuple[str, ...]
    pass_to_pass_success: tuple[str, ...]
    pass_to_pass_failure: tuple[str, ...]


def _test_passed(test_id: str, content: str) -> bool:
    return f"{test_id} PASSED" in content or f"{test_id} XFAIL" in content


def grade_eval_output(output: str, *, fail_to_pass: tuple[str, ...], pass_to_pass: tuple[str, ...]) -> EvalReport:
    content = output.split(START, 1)[1].split(END, 1)[0] if START in output and END in output else output
    f2p_success = tuple(test for test in fail_to_pass if _test_passed(test, content))
    f2p_failure = tuple(test for test in fail_to_pass if test not in f2p_success)
    p2p_success = tuple(test for test in pass_to_pass if _test_passed(test, content))
    p2p_failure = tuple(test for test in pass_to_pass if test not in p2p_success)
    return EvalReport(
        resolved=not f2p_failure and not p2p_failure,
        fail_to_pass_success=f2p_success,
        fail_to_pass_failure=f2p_failure,
        pass_to_pass_success=p2p_success,
        pass_to_pass_failure=p2p_failure,
    )
```

Add a focused helper in `sandbox_run.py` to copy and execute `spec.eval_script` and attach grading results to summary.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_swebench_grading.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swebench/grading.py src/coding_agent/swebench/sandbox_run.py tests/unit/test_swebench_grading.py
git commit -m "feat: grade official style swebench eval output"
```

## Task 9: Route Prepare And Run Through Official-Style TestSpec

**Files:**
- Modify: `src/coding_agent/swebench/sandbox_run.py`
- Modify: `tests/integration/test_swebench_sandbox_run.py`
- Modify: `tests/integration/test_swebench_batch_run.py`

- [ ] **Step 1: Write the failing integration test with fakes**

Add to `tests/integration/test_swebench_sandbox_run.py`:

```python
def test_run_swebench_task_uses_testspec_instance_image(tmp_path):
    record = _task_record()
    docker = FakeDocker(existing_images=set())

    with pytest.raises(SandboxedRunInputError, match="missing image"):
        run_swebench_task(
            task_record=record,
            docker=docker,
            backend=MockBackend(),
            budget=RunBudget(1, 30, 10),
            model_name="mock",
            output_dir=tmp_path,
            build_missing=False,
        )

    summary = run_swebench_task(
        task_record=record,
        docker=docker,
        backend=MockBackend(),
        budget=RunBudget(1, 30, 10),
        model_name="mock",
        output_dir=tmp_path / "built",
        build_missing=True,
    )

    assert docker.created_images[0].startswith("sweb.base.")
    assert docker.created_containers[0].image.startswith("sweb.eval.")
    assert summary.sandbox.task_sandbox.image_keys.instance.startswith("sweb.eval.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_swebench_sandbox_run.py::test_run_swebench_task_uses_testspec_instance_image -q`

Expected: FAIL because `run_swebench_task()` still requires `base_image` and has no `build_missing`.

- [ ] **Step 3: Write minimal implementation**

Change `run_swebench_task()`, `prepare_swebench_sandbox()`, and batch helpers to:

```python
def run_swebench_task(
    *,
    task_record: SwebenchTaskRecord,
    docker: DockerCli,
    backend: ModelBackend,
    budget: RunBudget,
    model_name: str,
    output_dir: str | Path,
    include_pass_to_pass: bool = False,
    build_missing: bool = False,
) -> RunSummary:
    spec = make_test_spec(task_record)
    ensure_test_spec_images(spec, docker=docker, build_missing=build_missing)
    prepared = prepare_swebench_sandbox_from_spec(
        spec=spec,
        docker=docker,
        output_dir=output_dir,
        include_pass_to_pass=include_pass_to_pass,
    )
    return solve_prepared_sandbox(
        task_record=task_record,
        sandbox=prepared.sandbox,
        docker=docker,
        backend=backend,
        budget=budget,
        model_name=model_name,
        output_dir=output_dir,
        include_pass_to_pass=include_pass_to_pass,
        cleanup=True,
    )
```

`prepare_swebench_sandbox_from_spec()` must call `TaskSandboxManager.prepare_from_test_spec()`, build validation with `validation_from_test_spec()`, and write `sandbox.json` with all three image keys.

Keep legacy repo-registry code paths in separate functions until contract tests are migrated.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_swebench_sandbox_run.py tests/integration/test_swebench_batch_run.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/swebench/sandbox_run.py tests/integration/test_swebench_sandbox_run.py tests/integration/test_swebench_batch_run.py
git commit -m "feat: run swebench tasks from official style images"
```

## Task 10: CLI Contract For Official-Style Image Preparation

**Files:**
- Modify: `src/coding_agent/cli.py`
- Create: `tests/contract/test_cli_swebench_prepare_images_contract.py`
- Modify: `tests/contract/test_cli_swebench_run_contract.py`

- [ ] **Step 1: Write the failing contract tests**

Add `tests/contract/test_cli_swebench_prepare_images_contract.py`:

```python
from coding_agent.cli import build_parser


def test_prepare_images_accepts_dataset_instances_and_build_missing_flag():
    parser = build_parser()

    args = parser.parse_args([
        "swebench",
        "prepare-images",
        "--dataset",
        "tasks.jsonl",
        "--instance-id",
        "django__django-12345",
        "--jobs",
        "2",
        "--build-missing",
    ])

    assert args.swebench_command == "prepare-images"
    assert args.build_missing is True
    assert args.jobs == 2
```

Add to `tests/contract/test_cli_swebench_run_contract.py`:

```python
def test_swebench_run_accepts_build_missing_without_registry():
    parser = build_parser()

    args = parser.parse_args([
        "swebench",
        "run",
        "--dataset",
        "tasks.jsonl",
        "--instance-id",
        "django__django-12345",
        "--max-steps",
        "1",
        "--timeout-seconds",
        "30",
        "--test-timeout-seconds",
        "10",
        "--output-dir",
        "out",
        "--backend",
        "mock",
        "--build-missing",
    ])

    assert args.registry is None
    assert args.build_missing is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/contract/test_cli_swebench_prepare_images_contract.py tests/contract/test_cli_swebench_run_contract.py -q`

Expected: FAIL because `prepare-images` does not exist and `swebench run --registry` is still required.

- [ ] **Step 3: Write minimal implementation**

Modify `build_parser()`:

- add `swebench prepare-images`
- make `swebench run --registry` optional for legacy mode
- add `--build-missing` to `run`, `prepare-sandbox`, and batch prepare commands
- call new image preparation function for `prepare-images`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/contract/test_cli_swebench_prepare_images_contract.py tests/contract/test_cli_swebench_run_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/cli.py tests/contract/test_cli_swebench_prepare_images_contract.py tests/contract/test_cli_swebench_run_contract.py
git commit -m "feat: add official style swebench image cli"
```

## Task 11: Final Verification And Legacy Compatibility

**Files:**
- Modify: `tests/unit/test_sandbox_registry.py`
- Modify: `tests/integration/test_sandbox_registry_integration.py`
- Modify: `specs/002-swebench-docker-sandbox/quickstart.md`
- Modify: `specs/002-swebench-docker-sandbox/contracts/cli-contract.md`

- [ ] **Step 1: Write failing compatibility expectations**

Add to `tests/contract/test_cli_swebench_run_contract.py`:

```python
def test_legacy_sandbox_register_still_parses():
    parser = build_parser()

    args = parser.parse_args([
        "sandbox",
        "register",
        "--repo",
        "django/django",
        "--image",
        "legacy-django:latest",
        "--repo-path",
        "/workspace/repo",
        "--official-compatible",
    ])

    assert args.command == "sandbox"
    assert args.sandbox_command == "register"
    assert args.repo == "django/django"


def test_official_style_swebench_run_registry_is_optional():
    parser = build_parser()

    args = parser.parse_args([
        "swebench",
        "run",
        "--dataset",
        "tasks.jsonl",
        "--instance-id",
        "django__django-12345",
        "--max-steps",
        "1",
        "--timeout-seconds",
        "30",
        "--test-timeout-seconds",
        "10",
        "--output-dir",
        "out",
        "--backend",
        "mock",
    ])

    assert args.registry is None
```

Add to `tests/unit/test_sandbox_registry.py`:

```python
def test_legacy_registry_validation_remains_available():
    base_image = load_base_image_from_registry_dict(
        {
            "repo": "django/django",
            "image": "legacy-django:latest",
            "repo_path": "/workspace/repo",
            "official_compatible": True,
            "validation_command_template": "python -m pytest {tests}",
        }
    )

    validate_base_image_for_run(base_image)
```

Add a docs assertion to `tests/contract/test_cli_swebench_prepare_images_contract.py`:

```python
def test_quickstart_documents_build_missing():
    text = Path("specs/002-swebench-docker-sandbox/quickstart.md").read_text(encoding="utf-8")

    assert "--build-missing" in text
    assert "prepare-images" in text
```

Run: `python -m pytest tests/unit/test_sandbox_registry.py tests/integration/test_sandbox_registry_integration.py tests/contract/test_cli_swebench_run_contract.py -q`

Expected: FAIL only where official-style CLI or docs are not updated.

- [ ] **Step 2: Update docs and compatibility code**

Update:

- `specs/002-swebench-docker-sandbox/quickstart.md`
- `specs/002-swebench-docker-sandbox/contracts/cli-contract.md`
- CLI help text for legacy registry commands to mark them as compatibility support

- [ ] **Step 3: Run focused suite**

Run:

```bash
python -m pytest tests/unit/test_swebench_testspec.py tests/unit/test_swebench_script_builders.py tests/unit/test_swebench_images.py tests/unit/test_swebench_validation.py tests/unit/test_swebench_grading.py tests/unit/test_container_tools.py tests/unit/test_sandbox_manager.py -q
```

Expected: PASS.

- [ ] **Step 4: Run contract and integration suite**

Run:

```bash
python -m pytest tests/contract/test_cli_swebench_prepare_images_contract.py tests/contract/test_cli_swebench_run_contract.py tests/integration/test_swebench_sandbox_run.py tests/integration/test_swebench_batch_run.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add specs/002-swebench-docker-sandbox/quickstart.md specs/002-swebench-docker-sandbox/contracts/cli-contract.md src tests
git commit -m "docs: update official style swebench sandbox workflow"
```

## Manual Validation

After automated tests pass, run one opt-in real Docker check on a small local fixture image:

```bash
coding-agent swebench prepare-images --dataset path/to/tasks.jsonl --instance-id django__django-12345 --build-missing --jobs 1
coding-agent swebench run --dataset path/to/tasks.jsonl --instance-id django__django-12345 --backend mock --max-steps 1 --timeout-seconds 60 --test-timeout-seconds 30 --output-dir out --build-missing
```

Expected:

- `sandbox.json` contains `base_image_key`, `env_image_key`, and `instance_image_key`.
- `summary.json`, `trajectory.jsonl`, `final.patch`, and `prediction.jsonl` are written.
- The container is created from `sweb.eval...`.
- The final patch does not include `test_patch` changes.
