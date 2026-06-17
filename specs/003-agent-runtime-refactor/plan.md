# Implementation Plan: Agent Runtime Environment Refactor

**Branch**: `003-agent-runtime-refactor` | **Date**: 2026-06-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/003-agent-runtime-refactor/spec.md`

## Summary

Refactor the benchmark agent runtime environment so new SWE-Bench task runs use
an official-style, source-backed runtime pipeline by default. The pipeline will
derive an adapted task spec from dataset metadata, resolve or build reusable
runtime layers, create a task-specific prepared environment, run the host-owned
agent against that environment, validate with source-backed benchmark semantics,
and preserve the existing artifact contract.

This plan intentionally does not expand into batch benchmark orchestration.
The first supported scope is the core SWE-Bench Lite repository set. Tasks
outside that set, or inside the set but missing source-backed metadata, fail
before agent execution with actionable messages. Existing prepared-workspace
runs remain supported. The legacy sandbox registry remains only through
explicit legacy commands and compatibility flows; new benchmark runs must not
use it.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Standard library (`argparse`, `dataclasses`, `json`,
`hashlib`, `pathlib`, `subprocess`, `tempfile`, `concurrent.futures` where
needed), existing `pyarrow>=16.0` for parquet datasets, Docker CLI through the
existing wrapper, pytest for tests. No runtime import dependency on the local
`SWE-bench/` checkout.

**Reference Sources**:

- User reference plan: `docs/superpowers/plans/2026-06-17-official-swebench-sandbox.md`
- User reference design: `docs/superpowers/specs/2026-06-17-official-swebench-sandbox-design.md`
- Existing project contract: `specs/002-swebench-docker-sandbox/spec.md`
- Existing project implementation contracts under `src/coding_agent/`
- Local upstream reference only: `SWE-bench/swebench/harness/test_spec/test_spec.py`
- Local upstream reference only: `SWE-bench/swebench/harness/test_spec/utils.py`
- Local upstream reference only: `SWE-bench/swebench/harness/docker_build.py`
- Local upstream reference only: `SWE-bench/swebench/harness/grading.py`
- Local upstream reference only: `SWE-bench/swebench/harness/constants/python.py`
- Docker CLI documentation for image build, container create/start/exec/cp,
  and container lifecycle behavior

**Storage**: Local filesystem artifacts under caller-provided run directories:
`trajectory.jsonl`, `trajectory.json`, `summary.json`, `final.patch`,
`prediction.jsonl`, and `sandbox.json`. Active prepared environments continue
to be indexed under `.coding-agent/active-sandboxes.json`. Runtime image/build
metadata is recorded in `sandbox.json` and summary metadata, not in the legacy
repo-keyed registry for new benchmark runs.

**Testing**: pytest unit, contract, and integration tests. Docker interactions
use fakes for default automated tests. Real Docker image preparation remains
manual or opt-in. New tests must prove red/green behavior and must not encode
fixture-only branches as implementation logic.

**Target Platform**: Developer workstation or CI runner that can run the Python
CLI. Docker is required only for real runtime preparation and execution.
Automated tests must run without a real Docker daemon unless explicitly marked
manual or opt-in.

**Project Type**: Single Python CLI/library project.

**Performance Goals**: Unsupported or missing-metadata tasks fail before model
execution. Existing runtime layers are reused instead of rebuilt. A developer
can inspect a run's runtime path, task metadata, validation source, and artifact
locations within 3 minutes from generated artifacts. The default single-task
runtime flow remains bounded by the existing run budget settings.

**Constraints**: New benchmark runs do not use the legacy sandbox registry.
Creating missing runtime layers is opt-in through an explicit flag. Batch
benchmark orchestration is out of scope. The host owns model calls, budgets,
trajectory, summary, prediction, and final patch export. The prepared task
environment owns repository reads, edits, searches, validation attempts, and
final diff extraction. Runtime behavior must be source-backed; static mappings
must cite upstream or project sources and must represent domain metadata.

**Scale/Scope**: First version supports the core SWE-Bench Lite repository set
where source-backed repository, environment, and validation metadata is present.
Required user-visible operation modes are: prepare runtime, direct run, and
continue prepared environment. Unknown repositories and missing source-backed
metadata fail before agent execution.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Clarification gate: PASS. `/speckit-clarify` resolved supported repository
  scope, behavior for missing source-backed metadata, legacy registry
  compatibility, required operation modes, and batch orchestration scope.
- Cohesion/coupling gate: PASS. Planned boundaries keep TestSpec adaptation,
  repo metadata, script generation, image resolution/building, grading, Docker
  command execution, sandbox lifecycle, container tools, and CLI parsing in
  separate modules. The agent loop remains independent of Docker/SWE-Bench
  details through the existing tool executor boundary.
- Source-backed behavior gate: PASS. Runtime behavior is derived from the
  reference plan, existing project contracts, and local upstream SWE-Bench
  harness files used as reference only. Missing source-backed metadata is a
  pre-agent input error, not guessed behavior.
- Test integrity gate: PASS. Static repo/version metadata is treated as domain
  metadata sourced from the upstream harness constants. Tests may use compact
  fixtures, but production behavior must not branch on fixture task IDs, known
  test names, or expected outputs.

## Project Structure

### Documentation (this feature)

```text
specs/003-agent-runtime-refactor/
|-- spec.md
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- contracts/
|   `-- cli-contract.md
`-- checklists/
    `-- requirements.md
```

### Source Code (repository root)

```text
scripts/
`-- prepare_swebench_repo_images.py        # Existing repo-image helper; remains compatibility/reference only

src/coding_agent/
|-- cli.py                                 # CLI parsing, command dispatch, exit-code mapping
|-- models.py                              # Shared persisted/runtime dataclasses
|-- agent.py                               # Host-owned model loop and artifact orchestration
|-- tools/
|   `-- executor.py                        # ToolExecutor protocol boundary
|-- sandbox/
|   |-- docker_cli.py                      # Docker CLI wrapper and build/copy helpers
|   |-- manager.py                         # Container lifecycle and prepared environment checks
|   |-- registry.py                        # Legacy registry compatibility path only
|   `-- tools.py                           # Container-backed read/edit/search/test executor
`-- swebench/
    |-- dataset.py                         # Dataset loading and task record normalization
    |-- testspec.py                        # New adapted source-backed task spec
    |-- repo_specs.py                      # New source-backed repo/version metadata
    |-- script_builders.py                 # New setup/eval script generation
    |-- images.py                          # New image graph resolution/build orchestration
    |-- grading.py                         # New official-style eval output grading
    |-- validation.py                      # Validation from adapted TestSpec
    |-- sandbox_run.py                     # Prepare/direct run/continue prepared orchestration
    `-- prediction.py                      # Existing prediction JSONL writer

tests/
|-- contract/
|-- integration/
`-- unit/
```

**Structure Decision**: Keep the current single-package project. Add focused
modules under `swebench/` for source-backed benchmark semantics and keep Docker
subprocess behavior under `sandbox/`. `cli.py` remains a dispatch layer only.
`agent.py` remains unaware of Docker, image keys, SWE-Bench metadata, and
runtime lineage.

## Phase 0 Research

See [research.md](./research.md). All planning unknowns are resolved in design
decisions. There are no unresolved clarification markers.

## Phase 1 Design

See [data-model.md](./data-model.md), [contracts/cli-contract.md](./contracts/cli-contract.md),
and [quickstart.md](./quickstart.md).

## Detailed Planning Notes

### Runtime Pipeline

1. Load a dataset row and normalize it into a benchmark task record.
2. Build an adapted source-backed task spec from the task record.
3. Resolve required repo/version metadata from source-backed repo specs.
4. Derive setup scripts, eval script, image keys, validation commands, and
   runtime lineage from the adapted task spec.
5. Check all required runtime images before model execution.
6. If `--build-missing` is absent and an image is missing, fail with exit 2.
7. If `--build-missing` is present, build missing images in base -> env ->
   instance order and record which images were built.
8. Create or reuse a task-specific prepared environment from the instance image.
9. Verify readiness: container exec works, repo is a worktree, task/repo/base
   revision match, workspace starts clean, validation source exists.
10. Run the host-owned agent with a container tool executor.
11. Run final official-style eval and grade `FAIL_TO_PASS` plus optional
    `PASS_TO_PASS`.
12. Export container diff as final patch without validation-only changes.
13. Write summary, prediction, trajectory, and sandbox metadata artifacts.

### Operation Modes

- `prepare-runtime`: prepare the runtime image graph for one or more selected
  supported tasks. This is not batch benchmark orchestration; it only prepares
  runtime layers.
- `prepare`: create and index a running task-specific prepared environment for
  one selected task.
- `run`: prepare as needed and solve one selected task in a single workflow.
- `continue-prepared`: solve using the indexed prepared environment for one
  selected task.

Existing `sandbox register/list` commands remain as explicit legacy
compatibility commands. Existing prepared-workspace `coding-agent run` remains
unchanged.

### Source-Backed Metadata Policy

Supported repo/version metadata is valid only when it is derived from upstream
SWE-Bench harness constants, official samples, official documentation, or an
existing project contract. Tests may use compact fixture records, but
production logic must call the same general metadata lookup path and must fail
on missing metadata.

### Compatibility Policy

Legacy registry behavior is preserved so existing users can still run explicit
legacy flows. New benchmark commands must not require `--registry` and must not
silently fall back to repo-keyed base images. If a legacy path is used, artifacts
must identify it as a compatibility path.

## Post-Design Constitution Check

- Clarification gate: PASS. Research and design artifacts encode all four
  clarifications from the spec; no planning unknowns remain.
- Cohesion/coupling gate: PASS. The plan adds narrowly scoped modules and
  avoids moving Docker/image logic into `agent.py` or parsing logic into
  `cli.py`.
- Source-backed behavior gate: PASS. `research.md` identifies source references
  and requires missing source-backed metadata to fail before agent execution.
- Test integrity gate: PASS. `research.md` and `data-model.md` distinguish
  source-backed domain metadata from test fixtures, and `quickstart.md` includes
  validation checks for unsupported metadata paths.

## Complexity Tracking

No constitution violations require justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | N/A |
