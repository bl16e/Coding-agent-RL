# Research: SWE-Bench Docker Sandbox

## Decision: Target official SWE-Bench-compatible environments

Use official SWE-Bench-compatible task environments as the required behavior for
registered repository base images. Local `data/Dockerfile.*` files may inform cache or
development experiments, but they do not define benchmark behavior.

**Rationale**: SWE-Bench documentation describes Docker-based evaluation as the
mechanism for consistent, reproducible results, and the harness exposes
`TestSpec` fields/properties for instance images, environment images, eval
scripts, `FAIL_TO_PASS`, and `PASS_TO_PASS`.

**Alternatives considered**:
- Use only local lightweight Dockerfiles: rejected because they may not match
  official dependency setup or test behavior.
- Build official images automatically during task execution: rejected by
  clarification; missing repository base images are pre-run configuration errors.

**Sources**:
- https://www.swebench.com/SWE-bench/guides/docker_setup/
- https://www.swebench.com/SWE-bench/api/harness/

## Decision: Host agent controller with container-backed tools

Run the agent control process on the host and execute repository tools against
the selected Docker task container.

**Rationale**: The host controller keeps model credentials, trajectory writes,
summary files, and prediction export outside the task sandbox. Docker provides
container lifecycle and operations such as run/create, exec, cp, diff, inspect,
and stop/remove through the CLI.

**Alternatives considered**:
- Run the entire agent in the container: rejected because model configuration
  and run artifacts would be coupled to each task environment.
- Support both modes now: rejected as unnecessary for the single-task MVP and
  likely to increase coupling.

**Sources**:
- https://docs.docker.com/reference/cli/docker/container/
- https://docs.docker.com/reference/cli/docker/container/run/

## Decision: Register existing repository base images before task execution

Add a registry of prepared repository base images keyed by repository. Task
runs look up a compatible image, create a task container from it, run
`git checkout <base_commit>` inside the repository path, and fail before model
execution if no image is registered or if the registered image is not marked
`official_compatible`.

**Rationale**: This matches the clarified workflow: configure a few reusable
repository base images first, then run tasks inside task containers created from them. It keeps environment
preparation separate from agent problem solving and makes missing setup errors
easy to diagnose.

**Alternatives considered**:
- Auto-build missing images during `swebench run`: rejected by clarification.
- Require one image per instance: rejected because the user wants reusable base
  images and the dataset contains many tasks per repository.

## Decision: Enforce explicit official-compatible image markers

Treat `official_compatible=true` as a runtime gate for sandboxed SWE-Bench
runs. The marker is stored in the registry and copied into `sandbox.json` and
`summary.json`.

**Rationale**: This prevents a locally convenient image from being silently used
as a benchmark environment when it has not been reviewed as official-compatible.
It also makes artifact review able to distinguish official-targeted runs from
local experiments.

**Alternatives considered**:
- Infer compatibility from image names: rejected because tags are not reliable
  evidence.
- Allow unmarked images with a warning: rejected because it can produce local
  runs that appear successful but are incompatible with official evaluation.

## Decision: Read local parquet task data with pyarrow

Use `pyarrow` to read local SWE-Bench Lite parquet files and map rows into a
validated task record. Avoid requiring pandas for the runtime path.

**Rationale**: The provided local dataset is parquet. The current environment
does not include a parquet engine, and pandas would add a broader dependency
than needed for row selection.

**Alternatives considered**:
- Require users to pre-convert parquet to JSONL: rejected because it adds manual
  setup to the workflow.
- Depend on pandas: rejected because `pyarrow` can read parquet directly and
  keeps the parsing module focused.

**Sources**:
- https://www.swebench.com/SWE-bench/guides/datasets/

## Decision: Default validation uses FAIL_TO_PASS only

Build the default allowed validation set from `FAIL_TO_PASS`. Include
`PASS_TO_PASS` only when the developer explicitly opts in.

**Rationale**: This directly follows clarification and keeps MVP runtime
bounded. `PASS_TO_PASS` remains available for regression validation when the
developer chooses broader checks.

**Alternatives considered**:
- Always include both lists: rejected because it can make validation much more
  expensive and was not the clarified default.
- Ignore `PASS_TO_PASS`: rejected because the spec requires opt-in regression
  validation support.

**Sources**:
- https://www.swebench.com/SWE-bench/guides/datasets/

## Decision: Prefer official TestSpec/eval script for validation commands

Convert `FAIL_TO_PASS` and optional `PASS_TO_PASS` identifiers into executable
commands through official SWE-Bench TestSpec/eval script behavior when that
source is available. If it is unavailable, require a registered
`validation_command_template`; otherwise fail before model execution.

**Rationale**: Test identifiers are not always shell commands. Guessing local
commands can create an agent that passes local tests but does not match the
official harness. An explicit template is acceptable only as a documented
fallback tied to the registered base image.

**Alternatives considered**:
- Always run `pytest <identifier>`: rejected because repository-specific test
  formats and official harness behavior may differ.
- Let the agent choose arbitrary tests: rejected because allowed validation must
  be tied to SWE-Bench metadata.

**Sources**:
- https://www.swebench.com/SWE-bench/api/harness/
