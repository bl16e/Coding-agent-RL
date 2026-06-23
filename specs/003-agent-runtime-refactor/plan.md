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
before agent execution with actionable messages. The first version exposes only
`prepare` and `run` for SWE-Bench benchmark runtime work; legacy registry,
legacy sandbox, and batch SWE-Bench runtime operations are rejected instead of
preserved as compatibility flows.

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
- Local upstream reference only: `SWE-bench/swebench/harness/test_spec/python.py`
- Local upstream reference only: `SWE-bench/swebench/harness/docker_build.py`
- Local upstream reference only: `SWE-bench/swebench/harness/grading.py`
- Local upstream reference only: `SWE-bench/swebench/harness/constants/__init__.py`
- Local upstream reference only: `SWE-bench/swebench/harness/constants/python.py`
- Local SWE-Bench Lite data: `data/dev-00000-of-00001.parquet`
- Local SWE-Bench Lite data: `data/test-00000-of-00001.parquet`
- Runtime image audit: `specs/003-agent-runtime-refactor/runtime-image-audit.md`
- Docker CLI documentation for image build, container create/start/exec/cp,
  and container lifecycle behavior

**Storage**: Local filesystem artifacts under caller-provided run directories:
`trajectory.jsonl`, `trajectory.json`, `summary.json`, `final.patch`,
`prediction.jsonl`, and `sandbox.json`. Active prepared environments continue
to be indexed under `.coding-agent/active-sandboxes.json`. Runtime image/build
metadata is recorded in `sandbox.json` and summary metadata, not in the legacy
repo-keyed registry.

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
benchmark orchestration and legacy SWE-Bench runtime operations are rejected.
The host owns model calls, budgets, trajectory, summary, prediction, and final
patch export. The prepared task environment owns repository reads, edits,
searches, validation attempts, and final diff extraction. Runtime behavior must
be source-backed; static mappings must cite upstream or project sources and
must represent domain metadata.

**Scale/Scope**: First version supports the core SWE-Bench Lite repository set
where source-backed repository, environment, and validation metadata is present.
Required user-visible benchmark operations are `prepare` and `run`. `prepare`
resolves the task into an adapted TestSpec, prepares or reuses Base/Env/Instance
image layers, and creates the task-specific prepared environment. `run` starts
the agent from a prepared environment and does not build images. Unknown
repositories, missing source-backed metadata, missing runtime layers during
prepare, and missing prepared environments during run fail before agent
execution.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Clarification gate: PASS. `/speckit-clarify` resolved supported repository
  scope, behavior for missing source-backed metadata, legacy registry removal,
  required operation modes, and batch orchestration scope.
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
|-- runtime-image-audit.md
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
`-- prepare_swebench_repo_images.py        # Existing repo-image helper; reference only

src/coding_agent/
|-- cli.py                                 # CLI parsing, command dispatch, exit-code mapping
|-- models.py                              # Shared persisted/runtime dataclasses
|-- agent.py                               # Host-owned model loop and artifact orchestration
|-- tools/
|   `-- executor.py                        # ToolExecutor protocol boundary
|-- sandbox/
|   |-- docker_cli.py                      # Docker CLI wrapper and build/copy helpers
|   |-- manager.py                         # Container lifecycle and prepared environment checks
|   |-- registry.py                        # Existing registry module; not used by new SWE-Bench runtime
|   `-- tools.py                           # Container-backed read/edit/search/test executor
`-- swebench/
    |-- dataset.py                         # Dataset loading and task record normalization
    |-- testspec.py                        # New adapted source-backed task spec
    |-- repo_specs.py                      # New source-backed repo/version metadata
    |-- script_builders.py                 # New setup/eval script generation
    |-- images.py                          # New image graph resolution/build orchestration
    |-- grading.py                         # New official-style eval output grading
    |-- validation.py                      # Validation from adapted TestSpec
    |-- sandbox_run.py                     # Prepare/run orchestration
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

1. During `prepare`, load a dataset row and normalize it into a benchmark task
   record.
2. Build an adapted source-backed TestSpec from the task record.
3. Resolve required repo/version metadata from source-backed repo specs.
4. Derive setup scripts, the official-style `eval_script`, Base/Env/Instance
   image keys, allowed in-run validation commands, and runtime lineage from the
   adapted TestSpec.
5. Check all required runtime images before model execution.
6. If `--build-missing` is absent and an image is missing, fail with exit 2.
7. If `--build-missing` is present, build missing images in base -> env ->
   instance order and record which images were built.
8. Create a task-specific prepared environment from the instance image, or
   replace the existing active prepared environment only when
   `--replace-existing` is supplied. Reuse is for Base/Env/Instance image layers,
   not for already-used task workspaces.
9. Verify readiness: container exec works, repo is a worktree, task/repo/base
   revision match, workspace starts clean, validation source exists.
10. For `run`, load and verify a ready prepared environment from the active
    index. Missing, mismatched, used, stopped, errored, or concurrently running
    prepared environments fail before agent execution.
11. Transition the prepared environment to running while the host-owned agent
    executes with a container tool executor; repository reads,
    edits, searches, and in-run validation commands execute inside the sandbox.
12. For final review, execute the adapted TestSpec `eval_script` inside the
    prepared environment and grade its official-style output for `FAIL_TO_PASS`
    plus optional `PASS_TO_PASS`.
13. Mark successful or limit-exhausted runs as used; mark post-start runtime
    failures as error while preserving partial diagnostics.
14. Export container diff as final patch without validation-only changes.
15. Write summary, prediction, trajectory, and sandbox metadata artifacts with
    self-contained runtime path, status transition, validation source, and
    artifact location data.

### Operation Modes

- `prepare`: for one selected supported task, resolve the dataset row into an
  adapted TestSpec, prepare or reuse Base/Env/Instance image layers, and create
  a running task-specific prepared environment. This command checks or builds
  image layers when explicitly allowed, writes `sandbox.json`, and indexes the
  environment in `.coding-agent/active-sandboxes.json`. If an active entry for
  the same instance already exists, `prepare` fails before environment changes
  unless `--replace-existing` is supplied. With `--replace-existing`, it stops or
  removes the prior prepared environment when present, replaces only the active
  index entry, writes new preparation metadata, and leaves prior run artifact
  directories intact. It does not select the final validation mode.
- `run`: solve one selected task by loading the indexed prepared environment,
  verifying task identity and base revision, and running the host-owned agent
  with command-based, container-confined repository tools. `run` does not build
  images or create a missing prepared environment; only a ready prepared
  environment may be consumed. Missing, mismatched, used, stopped, errored, or
  concurrently running prepared environments fail before agent execution and
  direct the developer to run `prepare --replace-existing`. Final review is
  performed by executing the adapted TestSpec `eval_script`, not by accepting
  arbitrary agent-requested validation commands as the benchmark outcome. `run
  --include-pass-to-pass` is the only first-version CLI switch that opts into
  regression validation.

### Prepared Environment State Policy

Prepared task environments are single-use for solving. The active index can
point to exactly one prepared environment per instance. `run` accepts only
`ready`, transitions it to `running` for the duration of agent execution, and
then records `used` for completed or limit-exhausted runs. Post-start runtime
failures record `error`. `used`, `stopped`, `error`, and `running` entries are
not reusable by `run`; they require a fresh `prepare --replace-existing`.
Without `--cleanup`, completed or limit-exhausted runs leave the active index
entry in `used` status. With `--cleanup`, run artifacts record `used -> stopped`,
the container is stopped or removed, and the active index entry is removed.
If a post-start runtime failure occurs with `--cleanup`, artifacts record
`running -> error` plus the cleanup action, the container is stopped or removed
when possible, and the active index entry is removed.
Reviewers inspect run-level `summary.json` and `sandbox.json` for runtime path,
status transition, task metadata, validation source, and artifact locations
without consulting the active index or legacy registry.

No legacy SWE-Bench runtime operation is preserved as a compatibility path.
Old registry-based, sandbox-based, or batch SWE-Bench entry points must be
removed from the supported benchmark runtime surface or rejected with an
unsupported-operation message.

### Source-Backed Metadata Policy

Supported repo/version metadata is valid only when it is derived from upstream
SWE-Bench harness constants, official samples, official documentation, or an
existing project contract. The first local SWE-Bench Lite audit scope is
recorded in `runtime-image-audit.md`: 323 rows, 18 repositories, 81
repo/version pairs, one base image key, 45 environment image keys, and 323
deterministic instance image keys from `data/*.parquet`. Tests may use compact
fixture records, but production logic must call the same general metadata
lookup path and must fail on missing metadata.

### Legacy Operation Policy

Legacy registry behavior is not preserved for this feature's benchmark runtime.
New benchmark commands must not accept `--registry`, must not silently fall
back to repo-keyed base images, and must reject old SWE-Bench runtime commands
instead of labeling them as compatibility paths.

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
