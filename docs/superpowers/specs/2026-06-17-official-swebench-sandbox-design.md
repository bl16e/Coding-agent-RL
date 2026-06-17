# Official SWE-Bench Sandbox Preparation Design

## Purpose

Update the SWE-Bench Docker sandbox workflow so environment and sandbox
preparation follow the official SWE-Bench harness model, while solving still
uses the existing host-orchestrated coding agent with repository tools executed
inside the task container.

The local `SWE-bench/` checkout is a reference only. Runtime behavior must live
inside `src/coding_agent` and must not require importing the local official
harness repository.

## Goals

- Generate official-style task specifications from local SWE-Bench dataset
  records.
- Use official-style image layering: base image, environment image, and
  instance image.
- Reuse environments at the repository/version/environment-script hash level.
- Create task containers from official-style instance images.
- Preserve the current agent runtime model: model calls, orchestration,
  trajectories, summaries, and predictions stay on the host; code tools run
  inside the container.
- Use official-style eval behavior for validation: reset test files, apply
  `test_patch`, run the repository-specific test command, parse
  `FAIL_TO_PASS`, and optionally include `PASS_TO_PASS`.
- Keep missing-image behavior predictable: fail by default and build missing
  images only when explicitly requested with `--build-missing`.
- Implement the change using strict TDD.

## Non-Goals

- Do not depend on the local `SWE-bench/` checkout at runtime.
- Do not move the coding agent controller into the container.
- Do not run automatic image builds unless the user explicitly enables them.
- Do not keep the repo-keyed base image registry as the default sandbox path.
- Do not broaden scope into full benchmark service orchestration.

## Architecture

The workflow is one pipeline with two responsibility phases.

First, the environment and sandbox preparation phase follows the official
SWE-Bench approach. The project generates an adapted `SwebenchTestSpec` from a
dataset record, derives setup scripts and eval scripts, resolves or builds the
base, env, and instance images, then creates a task container from the instance
image. The container starts with the repository, dependency environment, base
commit, and setup state prepared by the official-style image build process.

Second, the solve phase follows the current coding-agent approach. The
controller remains on the host and injects a `ContainerToolExecutor` pointed at
the prepared container. The agent reads files, applies patches, searches code,
and runs allowed tests inside the container. At the end, the host exports the
container repository diff and writes the existing artifacts:
`trajectory.jsonl`, `trajectory.json`, `final.patch`, `summary.json`, and
`prediction.jsonl`.

## TestSpec Adaptation

Add an internal SWE-Bench TestSpec adaptation layer under `src/coding_agent`.
It should produce the behavior needed by this project without importing the
official harness at runtime.

The adapted spec includes:

- `instance_id`
- `repo`
- `version`
- `base_commit`
- `repo_path`, defaulting to `/testbed`
- `env_name`, defaulting to `testbed`
- `fail_to_pass`
- `pass_to_pass`
- `test_patch`
- `repo_script`
- `env_script`
- `eval_script`
- `base_image_key`
- `env_image_key`
- `instance_image_key`
- `platform`
- repo/version dependency and test command metadata

The image keys should follow the official-style hierarchy:

- Base image key depends on language, architecture, and Docker specs.
- Environment image key depends on the environment setup script and Docker
  specs hash.
- Instance image key depends on the instance id and image tag.

## Image Build Flow

The build flow follows `base -> env -> instance`.

Base images install language-level tooling such as OS packages, Git, Python,
Miniconda, Node, or other language runtimes.

Environment images apply the generated environment setup script. For Python
tasks this means creating the `testbed` conda environment and installing
requirements, environment.yml dependencies, or explicit package sets according
to repo/version metadata.

Instance images apply the generated repository setup script. This clones the
repository, resets it to `base_commit`, removes remote access to newer upstream
state, runs setup/install commands, and leaves the repository in a clean
baseline state suitable for agent edits.

Prepare and run commands must check for required images first. If an image is
missing and `--build-missing` is false, the command fails before model
execution. If `--build-missing` is true, missing images are built in dependency
order and existing images are reused.

## Sandbox Preparation

Sandbox preparation creates containers from the official-style instance image,
not from a repo-keyed base image.

Readiness checks should verify:

- Container exec works.
- `repo_path` is a Git worktree.
- The repository corresponds to the requested task.
- The working tree is clean before the agent starts.
- The prepared baseline is associated with the task `base_commit`.

The `sandbox.json` artifact should record:

- `instance_id`
- `repo`
- `version`
- `base_commit`
- `container_name`
- `repo_path`
- `base_image_key`
- `env_image_key`
- `instance_image_key`
- build policy and whether missing images were built
- validation source and selected validation mode
- readiness check results

## Agent Runtime

The agent runtime remains host-orchestrated.

The host owns:

- model backend calls
- step budget and timeout tracking
- trajectory persistence
- summary and prediction artifacts
- batch state
- active sandbox index

The container owns:

- repository file reads
- patch application
- code search
- test execution
- final diff export

The agent loop must not import Docker-specific implementation details. Docker
behavior stays behind the sandbox manager, Docker CLI wrapper, and container
tool executor.

## Validation And Evaluation

Validation must use official-style semantics instead of a simple registered
command template.

The eval script should:

- reset test files touched by `test_patch`
- remove new test files introduced by `test_patch`
- apply `test_patch`
- emit start and end test output markers
- run the repo/version-specific test command
- reset test files again after execution

`FAIL_TO_PASS` is the default validation set. `PASS_TO_PASS` is included only
when explicitly requested.

The interactive `run_tests` tool should use commands derived from the adapted
TestSpec and should avoid permanently polluting the repository with
`test_patch`. If tests introduced by `test_patch` must be present, the executor
should apply them temporarily for that test run and restore the test files
afterward.

Final validation should run the full official-style eval script and parse its
output into the project summary. A task is resolved only when all required
`FAIL_TO_PASS` checks pass and, when enabled, all selected `PASS_TO_PASS` checks
remain passing.

## CLI Behavior

Update the SWE-Bench CLI around official-style images.

`coding-agent swebench prepare-images`:

- accepts dataset and instance ids
- generates adapted TestSpecs
- builds missing base, env, and instance images
- reuses existing images
- supports concurrent builds where safe

`coding-agent swebench prepare`:

- creates and leaves a running sandbox for subsequent solving
- fails by default when the required instance image is missing
- builds missing images only with `--build-missing`

`coding-agent swebench run`:

- prepares a sandbox and immediately solves it
- fails by default when the required instance image is missing
- builds missing images only with `--build-missing`

`coding-agent swebench solve-prepared`:

- continues to solve an active prepared sandbox
- uses the active sandbox index

The legacy repo-keyed base image registry can remain as a compatibility path
for existing local workflows, but it is no longer the default official-style
SWE-Bench path.

## Error Handling

- Invalid dataset metadata fails before model execution with configuration
  exit behavior.
- Missing required image without `--build-missing` fails before model execution.
- Image build failures preserve build logs and return runtime failure behavior.
- Sandbox creation or readiness failures preserve `sandbox.json` when possible.
- Model runtime failures preserve partial artifacts as current behavior allows.
- Artifact persistence failures keep the existing artifact-specific failure
  behavior.
- Final eval failures are recorded in `summary.json` with test output preserved.

## Testing Strategy

Implementation must follow strict TDD:

- Write one failing test for each new behavior.
- Run it and confirm it fails for the expected reason.
- Write the smallest implementation that passes.
- Run the focused test and then the relevant wider test set.
- Refactor only after green.

Planned test coverage:

- TestSpec generation from dataset records.
- Official-style base, env, and instance image key calculation.
- Environment image hash changes when environment scripts change.
- Eval script generation for modified and new test files.
- Missing image behavior without `--build-missing`.
- Image build order with `--build-missing`.
- Reuse of existing images.
- Container creation from `instance_image_key`.
- Sandbox metadata containing all three image keys.
- `run_tests` command allowlisting from the adapted TestSpec.
- Temporary `test_patch` application and cleanup during test execution.
- Final eval parsing for `FAIL_TO_PASS`.
- Optional `PASS_TO_PASS` inclusion.
- CLI contract behavior for prepare-images, prepare, run, and solve-prepared.

Unit tests should use fake Docker clients. Integration tests may use real
Docker only behind explicit opt-in markers or manual validation instructions.

## Migration

The current repo-keyed `BaseImage` registry path should be deprecated, not
deleted immediately. Existing tests and commands can keep exercising it until
the official-style path is complete, but new default SWE-Bench commands should
prefer adapted TestSpec image resolution.

Artifact shape should remain compatible where possible. Existing consumers of
`summary.json`, `final.patch`, `trajectory.jsonl`, and `prediction.jsonl`
should not need to change. `sandbox.json` may gain new fields for the official
image graph.
