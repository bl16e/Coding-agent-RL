# Implementation Plan: SWE-Bench Docker Sandbox

**Branch**: `002-swebench-docker-sandbox` | **Date**: 2026-06-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-swebench-docker-sandbox/spec.md`

## Summary

Extend the existing single-task coding agent with a SWE-Bench Lite Docker
sandbox workflow. The host agent controller keeps model access and artifacts on
the host, while repository tools execute against a selected task container.
Developers first register official SWE-Bench-compatible repository base images,
then run one selected dataset instance by reusing the image for that task's
repository, checking out the instance base commit inside the task container,
deriving default validation from `FAIL_TO_PASS`, and preserving the existing
trajectory, final patch, summary, and prediction artifacts.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Standard library for CLI, JSON, filesystem,
subprocess, and artifact persistence; Docker CLI for container lifecycle and
tool execution; `pyarrow` for local parquet dataset reads; official SWE-Bench
package/harness APIs as the source of environment/test-spec behavior where
installed; pytest for tests

**Storage**: Local filesystem artifacts under caller-provided output
directories; sandbox registry JSON file mapping repositories to configured base
image names, official compatibility markers, and validation command source
metadata; existing run artifacts `trajectory.jsonl`, `final.patch`,
`summary.json`, and `prediction.jsonl`

**Testing**: pytest unit, contract, and integration tests; Docker interactions
covered with fakes/mocks for unit and contract tests, with optional manual
quickstart validation against a real Docker image

**Target Platform**: Developer workstation or CI runner with Docker available;
Windows host is supported through Docker CLI commands, while task containers are
Linux SWE-Bench-compatible environments

**Project Type**: Single Python CLI/library project

**Performance Goals**: Reusing a registered repository base image avoids
rebuilding the base environment during task execution; a sandboxed run must fail
before model execution when a required image is missing; artifact inspection
must identify task id, repository, base commit, base image, validation set, and outcome in
under 3 minutes

**Constraints**: Task execution must not auto-create missing repository base
images; agent process runs on host; repository operations execute only inside
the selected task container; every new task run performs `git checkout` to the
selected base commit before agent actions; sandboxed SWE-Bench runs reject
registered images that are not marked `official_compatible`; default validation
includes `FAIL_TO_PASS` only; validation commands come from official
SWE-Bench TestSpec/eval script behavior or an explicit registered fallback
template; `PASS_TO_PASS` is opt-in; prepared-local-workspace `coding-agent run`
remains supported

**Scale/Scope**: One SWE-Bench Lite task per sandboxed run; base image
registration per repository; SWE-Bench Lite's 323 tasks map to about 18
repository base images; full benchmark batch orchestration and automatic
official image construction are out of scope for this feature

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Clarification gate: PASS. `/speckit-clarify` resolved official-compatible
  sandbox target, host/controller placement, sandbox reuse semantics, missing
  sandbox handling, and `PASS_TO_PASS` default behavior.
- Cohesion/coupling gate: PASS. Planned modules separate dataset loading,
  base image registry, Docker command execution, container-backed tools, and
  sandboxed run orchestration. Existing `agent.py` receives a small tool
  executor seam instead of Docker-specific behavior.
- Official behavior gate: PASS. Research names official SWE-Bench docs for
  Docker setup, dataset fields, and harness/TestSpec behavior, plus Docker CLI
  docs for container operations.

## Project Structure

### Documentation (this feature)

```text
specs/002-swebench-docker-sandbox/
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- contracts/
|   `-- cli-contract.md
|-- checklists/
|   `-- requirements.md
`-- spec.md
```

### Source Code (repository root)

```text
src/
`-- coding_agent/
    |-- cli.py                         # Add sandbox registry and SWE-Bench run commands
    |-- agent.py                       # Accept a pluggable tool executor
    |-- models.py                      # Add sandbox metadata/run summary fields
    |-- tools/
    |   |-- __init__.py                # Keep local tool dispatcher
    |   `-- executor.py                # ToolExecutor protocol and local executor
    |-- sandbox/
    |   |-- __init__.py
    |   |-- docker_cli.py              # Focused Docker CLI wrapper
    |   |-- registry.py                # Base image registry plus official compatibility metadata
    |   |-- manager.py                 # Task container lifecycle and git checkout checks
    |   `-- tools.py                   # Container-backed read/write/search/run_tests
    `-- swebench/
        |-- __init__.py
        |-- dataset.py                 # Local parquet task loading and validation
        |-- validation.py              # TestSpec/eval-script and fallback-template allowed commands
        |-- sandbox_run.py             # Host orchestration for one sandboxed task
        `-- prediction.py              # Existing prediction export remains

tests/
|-- contract/
|-- integration/
`-- unit/
```

**Structure Decision**: Keep the existing local workspace path intact and add
Docker support behind focused sandbox modules. The agent loop should depend on
an executor protocol for repository tools; Docker container behavior stays in
`sandbox/`, and SWE-Bench dataset/test metadata stays in `swebench/`.

**Phase 2 Responsibility Notes**: `tools/executor.py` owns only the tool
execution boundary and the prepared-workspace implementation. `agent.py`
receives a `ToolExecutor` but remains responsible for model/budget/trajectory
orchestration. Sandbox modules are currently package skeletons only; Docker
subprocess details must stay in `sandbox/docker_cli.py`, task container state in
`sandbox/manager.py`, registry persistence in `sandbox/registry.py`, and
container-backed tool semantics in `sandbox/tools.py`.

**Phase 3 Cohesion Review**: `agent.py` remains within its original
orchestration responsibility after executor injection; it does not import Docker
or SWE-Bench sandbox modules. The sandboxed workflow is split across
`swebench/sandbox_run.py` for host orchestration, `sandbox/manager.py` for
container lifecycle and checkout, `sandbox/tools.py` for container-backed tool
semantics, and `sandbox/docker_cli.py` for Docker subprocess mapping. No Phase 3
file currently needs to be split for responsibility size.

## Phase 0 Research

See [research.md](./research.md). All planning unknowns are resolved.

## Phase 1 Design

See [data-model.md](./data-model.md), [contracts/cli-contract.md](./contracts/cli-contract.md),
and [quickstart.md](./quickstart.md).

## Post-Design Constitution Check

- Clarification gate: PASS. Design artifacts encode every accepted
  clarification and introduce no new `NEEDS CLARIFICATION` items.
- Cohesion/coupling gate: PASS. Dataset parsing, base image registry
  persistence, Docker command execution, container tool behavior, and sandbox run orchestration are
  split by responsibility. `agent.py` remains an orchestration module and does
  not gain Docker subprocess details.
- Official behavior gate: PASS. Contracts and quickstart explicitly target
  official SWE-Bench-compatible environments, enforce official-compatible
  registry markers for sandboxed runs, and cite Docker CLI behavior used for
  container lifecycle and file/test operations.

## Complexity Tracking

No constitution violations require justification.

## Final Responsibility Audit

Reviewed on 2026-06-05 after implementing all user stories:

- `src/coding_agent/cli.py` owns argument parsing and exit-code mapping only.
  It delegates Docker registry work to `sandbox/registry.py`, dataset loading to
  `swebench/dataset.py`, validation construction to `swebench/validation.py`,
  and sandboxed run orchestration to `swebench/sandbox_run.py`.
- `src/coding_agent/agent.py` remains independent of Docker and SWE-Bench
  dataset details. It depends only on the `ToolExecutor` protocol for tool
  execution location.
- `src/coding_agent/models.py` contains shared dataclasses and serialization.
  It is the largest shared model file but still has one responsibility:
  persisted/runtime data contracts. A future split is appropriate only if
  sandbox-specific model contracts continue to grow.
- `src/coding_agent/sandbox/` is split by boundary: Docker CLI execution,
  registry persistence, container lifecycle, and container-backed tools.
- `src/coding_agent/swebench/` is split by dataset parsing, validation metadata,
  prediction export, and sandboxed task orchestration.

No file currently mixes Docker subprocess details with the agent loop, model
transport, or local prepared-workspace tool implementations.
