# Runtime Refactor Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the SWE-Bench runtime refactor so `swebench prepare` and `swebench run` use source-backed repository metadata, real official-style image preparation, official-style validation grading, and enforceable prepared-environment readiness.

**Architecture:** Keep the current module boundaries: repo/version metadata in `swebench/repo_specs.py`, script generation in `swebench/script_builders.py`, image build orchestration in `swebench/images.py`, grading in `swebench/grading.py`, and lifecycle orchestration in `swebench/sandbox_run.py`. Replace fixture-shaped behavior with compact source-backed adapters derived from local upstream SWE-Bench harness constants and log parsing behavior, without importing `SWE-bench/` at runtime.

**Tech Stack:** Python 3.11, pytest, pyarrow fixtures, Docker CLI wrapper fakes, standard library parsers and dataclasses.

---

## File Structure

- Modify `src/coding_agent/swebench/repo_specs.py`: store source-backed repo/version specs copied from audited upstream constants for supported pairs; expose lookup helpers without reaching into private fields.
- Modify `src/coding_agent/swebench/script_builders.py`: generate official-style repo/env/eval scripts with test patch markers, reset commands, and repo-specific test directives.
- Modify `src/coding_agent/swebench/images.py`: build real Dockerfiles for base/env/instance layers and pass the generated scripts to Docker.
- Modify `src/coding_agent/swebench/grading.py`: parse official-style eval logs using source-backed parser behavior and marker semantics.
- Modify `src/coding_agent/swebench/sandbox_run.py`: use real readiness checks, final eval scripts, safer active-index state transitions, and stricter run preflight checks.
- Modify `src/coding_agent/sandbox/docker_cli.py`: add small helpers only if needed for `docker cp`, `docker exec`, or atomic readiness commands.
- Modify `tests/helpers/swebench_fixtures.py`: add rows for Django, pytest, and a non-pytest repo/version shape.
- Modify `tests/unit/fakes/test_swebench_runtime_fakes.py`: record Dockerfile contents, command stdout/stderr/return code by command pattern, and container running state.
- Add/modify tests under `tests/unit/`, `tests/contract/`, and `tests/integration/` as listed below.

## Task 1: Source-Backed Repo/Version Metadata

**Files:**
- Modify: `src/coding_agent/swebench/repo_specs.py`
- Modify: `tests/unit/test_swebench_repo_specs.py`
- Modify: `tests/helpers/swebench_fixtures.py`

- [ ] **Step 1: Write failing metadata tests**

Add tests proving repo/version metadata is not a uniform placeholder:

```python
def test_repo_specs_preserve_django_test_command_from_upstream_constants():
    spec = DEFAULT_REPO_SPECS.require("django/django", "3.0")

    assert spec.test_command.startswith("./tests/runtests.py")
    assert "--settings=test_sqlite" in spec.test_command
    assert spec.source_reference.endswith("SWE-bench/swebench/harness/constants/python.py")
    assert spec.review_status is RepoSpecReviewStatus.SOURCE_BACKED


def test_repo_specs_preserve_pytest_command_shape():
    spec = DEFAULT_REPO_SPECS.require("pytest-dev/pytest", "6.0")

    assert spec.test_command.startswith("pytest")
    assert "-rA" in spec.test_command
    assert spec.test_command != "python -m pytest"


def test_repo_specs_do_not_claim_source_backed_when_version_missing():
    with pytest.raises(MissingRepoSpecError, match="missing source-backed metadata"):
        DEFAULT_REPO_SPECS.require("django/django", "0.0")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests\unit\test_swebench_repo_specs.py -q
```

Expected: fail because `django/django@3.0` currently returns `python -m pytest` and source reference points only to the audit document.

- [ ] **Step 3: Implement source-backed metadata**

Replace uniform `load_audit_repo_specs()` construction with explicit metadata derived from `SWE-bench/swebench/harness/constants/python.py` for all repo/version pairs present in `runtime-image-audit.md`. Use compact helpers to avoid a giant flat table:

```python
UPSTREAM_PYTHON_CONSTANTS = "SWE-bench/swebench/harness/constants/python.py"

_DJANGO_TEST = "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1"
_PYTEST_TEST = "pytest -rA"

REPO_VERSION_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("django/django", "3.0"): {"packages": ("pytest",), "install_commands": ("python -m pip install -e .",), "test_command": _DJANGO_TEST},
    ("django/django", "3.1"): {"packages": ("pytest",), "install_commands": ("python -m pip install -e .",), "test_command": _DJANGO_TEST},
    ("pytest-dev/pytest", "6.0"): {"pip_packages": ("pytest",), "install_commands": ("python -m pip install -e .",), "test_command": _PYTEST_TEST},
}
```

Then extend this table to every audited pair before claiming full support. If a pair is in the audit but not in `REPO_VERSION_OVERRIDES`, mark it unsupported instead of silently using defaults.

- [ ] **Step 4: Run metadata tests to verify GREEN**

Run:

```powershell
python -m pytest tests\unit\test_swebench_repo_specs.py tests\unit\test_swebench_dataset.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src\coding_agent\swebench\repo_specs.py tests\unit\test_swebench_repo_specs.py tests\helpers\swebench_fixtures.py
git commit -m "fix: use source-backed swebench repo metadata"
```

## Task 2: Official-Style Script Generation

**Files:**
- Modify: `src/coding_agent/swebench/script_builders.py`
- Modify: `src/coding_agent/swebench/testspec.py`
- Modify: `tests/unit/test_swebench_script_builders.py`
- Modify: `tests/unit/test_swebench_testspec.py`

- [ ] **Step 1: Write failing script tests**

Add tests for Django directive conversion, test patch apply/reset, and eval markers:

```python
def test_eval_script_for_django_uses_runtests_directives_and_markers():
    repo_spec = RepoVersionSpec(
        repo="django/django",
        version="3.0",
        language="py",
        test_command="./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1",
        source_reference="SWE-bench/swebench/harness/constants/python.py",
        review_status=RepoSpecReviewStatus.SOURCE_BACKED,
        install_commands=("python -m pip install -e .",),
    )
    test_patch = "diff --git a/tests/model_fields/test_jsonfield.py b/tests/model_fields/test_jsonfield.py\n"

    script = build_eval_script_contract(repo_spec, ("tests/model_fields/test_jsonfield.py::TestJSONField::test_key_transform",), test_patch=test_patch, repo_path="/testbed", base_commit="abc123")

    assert "START_TEST_OUTPUT" in script
    assert "END_TEST_OUTPUT" in script
    assert "git apply -v -" in script
    assert "git checkout abc123 tests/model_fields/test_jsonfield.py" in script
    assert "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1" in script


def test_eval_script_rejects_empty_test_patch_when_directives_cannot_be_derived():
    with pytest.raises(ScriptMetadataError, match="test_patch"):
        build_eval_script_contract(repo_spec, ("tests/test_issue.py::test_fix",), test_patch="", repo_path="/testbed", base_commit="abc123")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests\unit\test_swebench_script_builders.py tests\unit\test_swebench_testspec.py -q
```

Expected: fail because current script builder only concatenates `test_command + FAIL_TO_PASS` and does not apply/reset test patches or emit official markers.

- [ ] **Step 3: Implement script builders**

Implement helpers modeled on upstream `make_repo_script_list_py`, `make_env_script_list_py`, and `make_eval_script_list_py`:

```python
START_TEST_OUTPUT = ">>>>> Start Test Output"
END_TEST_OUTPUT = ">>>>> End Test Output"

def build_eval_script_contract(repo_spec: RepoVersionSpec, fail_to_pass: tuple[str, ...], *, test_patch: str, repo_path: str, base_commit: str) -> str:
    modified_files = tuple(_modified_files_from_patch(test_patch))
    new_files = tuple(_new_files_from_patch(test_patch))
    directives = tuple(_test_directives_from_patch(repo_spec.repo, test_patch))
    if not directives:
        raise ScriptMetadataError("test_patch must contain test directives")
    reset_commands = []
    if modified_files:
        reset_commands.append(f"git checkout {base_commit} {' '.join(modified_files)}")
    if new_files:
        reset_commands.append(f"rm -f {' '.join(new_files)}")
    test_command = repo_spec.test_command + " " + " ".join(directives)
    return "\n".join([
        "set -euxo pipefail",
        f"cd {repo_path}",
        *reset_commands,
        "git apply -v - <<'EOF_114329324912'",
        test_patch,
        "EOF_114329324912",
        f": '{START_TEST_OUTPUT}'",
        test_command,
        f": '{END_TEST_OUTPUT}'",
        *reset_commands,
        "",
    ])
```

Update `build_adapted_testspec()` to pass `test_patch`, `repo_path`, and `base_commit`.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
python -m pytest tests\unit\test_swebench_script_builders.py tests\unit\test_swebench_testspec.py tests\unit\test_swebench_validation.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src\coding_agent\swebench\script_builders.py src\coding_agent\swebench\testspec.py tests\unit\test_swebench_script_builders.py tests\unit\test_swebench_testspec.py
git commit -m "fix: generate official style swebench scripts"
```

## Task 3: Real Runtime Image Build Orchestration

**Files:**
- Modify: `src/coding_agent/swebench/images.py`
- Modify: `src/coding_agent/sandbox/docker_cli.py`
- Modify: `tests/unit/test_swebench_images.py`
- Modify: `tests/unit/fakes/test_swebench_runtime_fakes.py`

- [ ] **Step 1: Write failing image build tests**

Add tests that inspect Dockerfile content, not just call order:

```python
def test_build_missing_images_uses_testspec_scripts_in_dockerfiles():
    docker = FakeOfficialRuntimeDocker()
    plan = plan_image_graph(_testspec(), existing_images=set(), build_missing=True)

    build_missing_images(_testspec(repo_script="git clone repo", env_script="conda create -n testbed python=3.11 -y", eval_script="echo eval"), docker=docker, plan=plan)

    dockerfiles = {call[1][0]: call[1][1] for call in docker.calls if call[0] == "build_image"}
    assert "FROM ubuntu" in dockerfiles["sweb.base.py.x86_64:latest"]
    assert "conda create -n testbed python=3.11 -y" in dockerfiles["sweb.env.py.x86_64.hash:latest"]
    assert "git clone repo" in dockerfiles["sweb.eval.x86_64.django__django-11099:latest"]
    assert "echo eval" in dockerfiles["sweb.eval.x86_64.django__django-11099:latest"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests\unit\test_swebench_images.py -q
```

Expected: fail because Dockerfiles are literal placeholders.

- [ ] **Step 3: Implement real Dockerfile generation**

Add focused builders:

```python
def base_dockerfile(testspec: AdaptedTestSpec) -> str:
    return "\n".join([
        "FROM ubuntu:22.04",
        "ENV DEBIAN_FRONTEND=noninteractive",
        "RUN apt-get update && apt-get install -y git curl ca-certificates bash && rm -rf /var/lib/apt/lists/*",
        "",
    ])

def env_dockerfile(testspec: AdaptedTestSpec) -> str:
    return "\n".join([
        f"FROM {testspec.base_image_key}",
        "SHELL [\"/bin/bash\", \"-lc\"]",
        "RUN cat > /tmp/setup_env.sh <<'EOF_ENV'",
        testspec.env_script,
        "EOF_ENV",
        "RUN bash /tmp/setup_env.sh",
        "",
    ])

def instance_dockerfile(testspec: AdaptedTestSpec) -> str:
    return "\n".join([
        f"FROM {testspec.env_image_key}",
        "SHELL [\"/bin/bash\", \"-lc\"]",
        "RUN cat > /tmp/setup_repo.sh <<'EOF_REPO'",
        testspec.repo_script,
        "EOF_REPO",
        "RUN bash /tmp/setup_repo.sh",
        "RUN cat > /opt/swebench_eval.sh <<'EOF_EVAL'",
        testspec.eval_script,
        "EOF_EVAL",
        "RUN chmod +x /opt/swebench_eval.sh",
        "",
    ])
```

Wire `build_missing_images()` to use these builders in base -> env -> instance order.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
python -m pytest tests\unit\test_swebench_images.py tests\integration\test_swebench_official_runtime.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src\coding_agent\swebench\images.py src\coding_agent\sandbox\docker_cli.py tests\unit\test_swebench_images.py tests\unit\fakes\test_swebench_runtime_fakes.py
git commit -m "fix: build real official style runtime images"
```

## Task 4: Official-Style Eval Log Grading

**Files:**
- Modify: `src/coding_agent/swebench/grading.py`
- Modify: `src/coding_agent/swebench/sandbox_run.py`
- Modify: `tests/unit/test_swebench_grading.py`
- Modify: `tests/integration/test_swebench_official_runtime.py`

- [ ] **Step 1: Write failing grading tests**

Add tests using real marker-style logs:

```python
def test_parse_eval_report_accepts_marker_wrapped_pytest_output():
    output = "\n".join([
        "setup text",
        ">>>>> Start Test Output",
        "tests/test_issue.py::test_fix PASSED",
        "tests/test_regression.py::test_old PASSED",
        ">>>>> End Test Output",
    ])

    report = parse_eval_report(
        output,
        repo="pytest-dev/pytest",
        version="6.0",
        fail_to_pass=("tests/test_issue.py::test_fix",),
        pass_to_pass=("tests/test_regression.py::test_old",),
        raw_output_artifact="eval.log",
    )

    assert report.resolved is True
    assert report.fail_to_pass_success == ("tests/test_issue.py::test_fix",)


def test_parse_eval_report_missing_markers_is_validation_failure():
    with pytest.raises(EvalOutputParseError, match="missing official eval markers"):
        parse_eval_report("tests/test_issue.py::test_fix PASSED", repo="pytest-dev/pytest", version="6.0", fail_to_pass=("tests/test_issue.py::test_fix",))
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests\unit\test_swebench_grading.py -q
```

Expected: fail because parser currently requires JSON `tests_status`.

- [ ] **Step 3: Implement log parser behavior**

Implement a small source-backed parser map for first supported repo families:

```python
START_TEST_OUTPUT = ">>>>> Start Test Output"
END_TEST_OUTPUT = ">>>>> End Test Output"

def _extract_official_test_output(output: str) -> str:
    if START_TEST_OUTPUT not in output or END_TEST_OUTPUT not in output:
        raise EvalOutputParseError("missing official eval markers")
    return output.split(START_TEST_OUTPUT, 1)[1].split(END_TEST_OUTPUT, 1)[0]

def _parse_pytest_statuses(test_output: str) -> dict[str, str]:
    statuses = {}
    for line in test_output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1] in {"PASSED", "FAILED", "ERROR", "XFAIL"}:
            statuses[parts[0]] = parts[-1]
    return statuses
```

Route Django and pytest-family output through parser functions based on repo. Keep existing JSON parsing only as a backward-compatible test fixture parser if the output starts with `{`.

Update `_run_final_eval()` to call `parse_eval_report(..., repo=prepared.repo, version=prepared.version, ...)`.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
python -m pytest tests\unit\test_swebench_grading.py tests\integration\test_swebench_official_runtime.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src\coding_agent\swebench\grading.py src\coding_agent\swebench\sandbox_run.py tests\unit\test_swebench_grading.py tests\integration\test_swebench_official_runtime.py
git commit -m "fix: grade official style eval logs"
```

## Task 5: Prepared Runtime Readiness and Active Index State

**Files:**
- Modify: `src/coding_agent/swebench/sandbox_run.py`
- Modify: `tests/integration/test_swebench_official_runtime.py`
- Modify: `tests/integration/test_errored_run_diagnostics.py`
- Modify: `tests/unit/fakes/test_swebench_runtime_fakes.py`

- [ ] **Step 1: Write failing readiness tests**

Add tests for real preflight checks:

```python
def test_prepare_fails_when_workspace_is_dirty(tmp_path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FakeOfficialRuntimeDocker(
        present_images=set(PRESENT_IMAGES),
        exec_results={
            ("git", "-C", "/testbed", "status", "--porcelain"): DockerResult("M app.py\n", "", 0),
        },
    )

    with pytest.raises(SandboxedRunInputError, match="workspace is not clean"):
        prepare_official_swebench_runtime(dataset_path=dataset, instance_id="django__django-11099", docker=docker, output_dir=tmp_path / "prepare", active_index_path=tmp_path / ".coding-agent" / "active-sandboxes.json")


def test_run_fails_before_agent_when_container_is_not_running(tmp_path):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet")
    docker = FakeOfficialRuntimeDocker(present_images=set(PRESENT_IMAGES), running_containers=set())
    index_path = tmp_path / ".coding-agent" / "active-sandboxes.json"
    write_ready_active_index(index_path, container_name="missing-container")

    with pytest.raises(SandboxedRunInputError, match="container is not ready"):
        run_prepared_swebench_runtime(dataset_path=dataset, instance_id="django__django-11099", docker=docker, backend=MockBackend(), budget=RunBudget(1, 60, 10), model_name="mock-model", output_dir=tmp_path / "run", active_index_path=index_path)

    assert not (tmp_path / "run" / "trajectory.jsonl").exists()
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests\integration\test_swebench_official_runtime.py::test_prepare_fails_when_workspace_is_dirty tests\integration\test_swebench_official_runtime.py::test_run_fails_before_agent_when_container_is_not_running -q
```

Expected: fail because readiness is currently hardcoded and run preflight trusts the active index.

- [ ] **Step 3: Implement real readiness checks**

Add helpers:

```python
def _official_ready_checks(docker: DockerCli, prepared: PreparedTaskEnvironment, testspec: AdaptedTestSpec) -> dict[str, Any]:
    docker.exec(prepared.container_name, ["true"])
    head = docker.exec(prepared.container_name, ["git", "-C", prepared.repo_path, "rev-parse", "HEAD"]).stdout.strip()
    if head != prepared.base_commit:
        raise SandboxedRunInputError("prepared environment base commit does not match requested task")
    status = docker.exec(prepared.container_name, ["git", "-C", prepared.repo_path, "status", "--porcelain"]).stdout.strip()
    if status:
        raise SandboxedRunInputError("prepared workspace is not clean")
    return {
        "container_exec": {"ok": True},
        "base_commit": {"ok": True, "base_commit": head},
        "workspace_clean": {"ok": True},
        "validation_source": {"ok": True, "source": testspec.repo_version_source},
    }
```

Call this during `prepare_official_swebench_runtime()` before saving the active index, and call a lightweight equivalent during `run_prepared_swebench_runtime()` before writing `running`.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
python -m pytest tests\integration\test_swebench_official_runtime.py tests\integration\test_errored_run_diagnostics.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src\coding_agent\swebench\sandbox_run.py tests\integration\test_swebench_official_runtime.py tests\integration\test_errored_run_diagnostics.py tests\unit\fakes\test_swebench_runtime_fakes.py
git commit -m "fix: verify prepared runtime readiness"
```

## Task 6: Regression and Contract Coverage

**Files:**
- Modify: `tests/contract/test_cli_swebench_runtime_contract.py`
- Modify: `tests/contract/test_cli_swebench_run_contract.py`
- Modify: `specs/003-agent-runtime-refactor/quickstart.md`

- [ ] **Step 1: Add contract tests for unsupported partial metadata**

```python
def test_prepare_rejects_audited_pair_without_repo_spec_override(tmp_path, monkeypatch, capsys):
    dataset = write_swebench_parquet(tmp_path / "dataset.parquet", rows=[swebench_row(repo="supported/repo", version="1.0")])

    exit_code = main(["swebench", "prepare", "--dataset", str(dataset), "--instance-id", "django__django-11099", "--output-dir", str(tmp_path / "prepare")])

    assert exit_code == 2
    assert "missing source-backed metadata" in capsys.readouterr().err
```

- [ ] **Step 2: Run focused contract tests**

Run:

```powershell
python -m pytest tests\contract\test_cli_swebench_runtime_contract.py tests\contract\test_cli_swebench_run_contract.py -q
```

Expected: pass after earlier tasks.

- [ ] **Step 3: Update quickstart verification section**

Record the new focused commands:

```powershell
python -m pytest tests\unit\test_swebench_repo_specs.py tests\unit\test_swebench_script_builders.py tests\unit\test_swebench_images.py tests\unit\test_swebench_grading.py -q
python -m pytest tests\integration\test_swebench_official_runtime.py tests\integration\test_errored_run_diagnostics.py -q
python -m pytest tests\contract\test_cli_swebench_runtime_contract.py tests\contract\test_cli_swebench_run_contract.py -q
python -m pytest -q
```

- [ ] **Step 4: Run full verification**

Run:

```powershell
python -m pytest -q
git diff --check -- specs\003-agent-runtime-refactor src tests README.md docs\superpowers\plans\2026-06-29-runtime-refactor-remediation.md
```

Expected: all tests pass and no whitespace errors.

- [ ] **Step 5: Commit**

```powershell
git add tests\contract\test_cli_swebench_runtime_contract.py tests\contract\test_cli_swebench_run_contract.py specs\003-agent-runtime-refactor\quickstart.md
git commit -m "test: cover official runtime remediation contracts"
```

## Self-Review

- Spec coverage: The plan covers source-backed metadata, official image layers, source-backed validation/grading, prepared environment readiness, active-index preflight, CLI contracts, and artifact verification.
- Placeholder scan: No task is delegated to a vague "add tests" instruction; each task includes concrete target files, example failing tests, commands, and expected failure reasons.
- Type consistency: The plan keeps existing public function names where possible. New parser parameters are `repo` and `version`; `_run_final_eval()` must be updated in the same task that changes `parse_eval_report()`.

