# Feature Specification: Agent Runtime Environment Refactor

**Feature Branch**: `003-agent-runtime-refactor`

**Created**: 2026-06-17

**Status**: Draft

**Input**: User description: "参考docs/superpowers/plans/2026-06-17-official-swebench-sandbox.md 这个文档对我当前项目的agent 运行环境部分 的整体流程和做法 进行重构"

## Clarifications

### Session 2026-06-17

- Q: What is the first supported benchmark task scope for this refactor? → A: Core SWE-Bench Lite repository set; unknown repositories fail with an explicit unsupported message.
- Q: How should a core repository/version be handled when source-backed metadata is unavailable? → A: Treat it as unsupported and fail before agent execution with a missing source-backed metadata message.
- Q: What legacy sandbox registry compatibility level is required? → A: Do not keep old benchmark runtime operations as compatibility paths; the first version exposes only `prepare` and `run`.
- Q: Which user-visible operation modes are required in the first version? → A: Two operations only: prepare all required environments, then run the agent from a prepared environment; batch benchmark orchestration is out of scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prepare Official-Style Runtime Environments (Priority: P1)

A developer wants the agent run environment to be prepared through a predictable,
official-style workflow so each selected benchmark task starts from a clean,
task-specific environment rather than a manually configured or repository-keyed
shortcut.

**Why this priority**: Environment preparation is the foundation for every
agent run. Without it, later solving, validation, and artifact review cannot be
trusted as benchmark-compatible.

**Independent Test**: Can be tested by selecting one supported task, preparing
its runtime environment, and verifying that the prepared environment records
the task identity, repository identity, base revision, environment lineage, and
readiness status before any agent action begins.

**Acceptance Scenarios**:

1. **Given** a supported task with required metadata, **When** the developer
   prepares its runtime environment, **Then** the system produces a ready
   task-specific environment tied to that task and its base revision.
2. **Given** a required runtime layer is missing, **When** the developer prepares
   the task without explicitly allowing missing layers to be created, **Then**
   the system stops before agent execution and reports the missing layer.
3. **Given** reusable runtime layers already exist, **When** another task can
   share those layers, **Then** the system reuses them while still creating a
   task-specific starting point.

---

### User Story 2 - Run Agent Work Through the Prepared Environment (Priority: P2)

A developer wants to run a benchmark task from a prepared task environment
while preserving the existing run artifacts, budgets, model interaction flow,
and repository-tool behavior.

**Why this priority**: The refactor must improve runtime preparation without
breaking the agent's core solving workflow or existing artifact contract.

**Independent Test**: Can be tested by preparing one task, running the agent
against that prepared environment, and confirming that code inspection, edits,
search, and allowed validation occur only in the selected environment while
trajectory, summary, final patch, and prediction artifacts remain available to
the developer.

**Acceptance Scenarios**:

1. **Given** a prepared task environment, **When** the developer starts an agent
   run, **Then** the agent operates only on the selected task workspace.
2. **Given** a selected task has not already been prepared, **When** the
   developer starts a run, **Then** the system stops before agent execution and
   reports that the task environment must be prepared first.
3. **Given** the selected task's prepared environment has already been used,
   stopped, errored, or is currently marked as running by another run, **When**
   the developer starts a run, **Then** the system stops before agent execution
   and requires a fresh `prepare --replace-existing`.
4. **Given** the agent completes or exhausts its configured limits, **When** the
   run ends, **Then** the developer receives the same core artifact set as the
   current project flow plus environment metadata.
5. **Given** an environment failure occurs after the run has started, **When**
   the run stops, **Then** partial diagnostic artifacts are preserved for
   inspection.

---

### User Story 3 - Validate With Source-Backed Benchmark Semantics (Priority: P3)

A developer wants validation to follow the reference plan's official-style task
semantics so test execution reflects the selected task's benchmark metadata
instead of ad hoc command templates or current test fixtures.

**Why this priority**: Benchmark credibility depends on validation matching the
task's expected behavior, not on test-specific shortcuts.

**Independent Test**: Can be tested by selecting a task with fix-verification
metadata, running validation, and verifying that accepted validation attempts
come from the selected task's metadata, regression checks are opt-in, and
test-added files do not permanently pollute the workspace.

**Acceptance Scenarios**:

1. **Given** a task with fix-verification metadata, **When** validation is
   configured for a run, **Then** the default allowed validation set uses the
   task's fix-verification checks.
2. **Given** the developer explicitly enables regression checks, **When**
   validation is configured, **Then** the selected regression checks are
   included and reported separately from the default checks.
3. **Given** a validation request is not part of the selected task's allowed
   validation set, **When** the agent asks to run it, **Then** the request is
   rejected and recorded.

---

### User Story 4 - Enforce Only Two Benchmark Operations (Priority: P4)

A developer wants the refactored SWE-Bench runtime CLI to expose only the
current design's two benchmark operations so old registry, sandbox, and batch
entry points cannot be confused with the official-style workflow.

**Why this priority**: Allowing old benchmark runtime operations to remain as
compatibility paths would keep the ambiguity this refactor is intended to
remove.

**Independent Test**: Can be tested by checking CLI parsing and help for
benchmark commands, verifying that only `prepare` and `run` are accepted, and
confirming that old registry, sandbox, and batch SWE-Bench commands fail with a
clear unsupported-operation message.

**Acceptance Scenarios**:

1. **Given** a developer opens SWE-Bench runtime help, **When** the available
   operations are listed, **Then** only `prepare` and `run` are presented for
   benchmark runtime work.
2. **Given** a developer invokes an old SWE-Bench runtime command such as
   `prepare-sandbox`, `solve-sandbox`, `prepare-sandboxes`, or
   `solve-sandboxes`, **When** the CLI handles the request, **Then** it rejects
   the command as unsupported for this feature.
3. **Given** a developer passes legacy registry input such as `--registry` to
   the new `prepare` or `run` operation, **When** arguments are parsed, **Then**
   the command fails before agent execution with an unsupported legacy-runtime
   message.

### Edge Cases

- Selected task metadata is missing, malformed, or incomplete.
- The referenced official behavior or sample is ambiguous for a supported task.
- A required runtime layer is missing and the developer did not opt into
  creating missing layers.
- Runtime preparation starts but fails before the agent begins.
- Runtime preparation succeeds but readiness checks show an incorrect task
  identity, dirty workspace, or wrong base revision.
- `prepare` finds an existing active entry for the same instance.
- `run` finds an active entry that is already used, stopped, errored, or marked
  running by another run.
- Agent work starts and the runtime environment later fails.
- Validation metadata is unavailable, empty, or cannot be translated into
  allowed validation attempts.
- Validation introduces task test files that must be removed or reset after the
  validation attempt.
- Existing run artifacts are present when a new task run starts.
- A developer attempts a legacy registry, legacy sandbox, or batch benchmark
  operation in this feature scope.
- Static task metadata or mappings are needed and must be distinguished from
  hardcoded test shortcuts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a default benchmark runtime workflow based
  on the reference plan at `docs/superpowers/plans/2026-06-17-official-swebench-sandbox.md`.
- **FR-002**: The system MUST prepare each benchmark task from task metadata
  that identifies the task, repository, version or equivalent grouping, base
  revision, validation metadata, and task-specific patch metadata when present.
- **FR-002a**: The first supported scope MUST cover the core SWE-Bench Lite
  repository set; tasks outside that supported set MUST fail before agent
  execution with an explicit unsupported-repository message.
- **FR-002b**: Tasks inside the supported repository set but missing
  source-backed repository, environment, or validation metadata MUST fail before
  agent execution with an explicit missing-metadata message.
- **FR-003**: The system MUST record enough runtime lineage for a reviewer to
  distinguish reusable layers from the task-specific environment used for a run.
- **FR-004**: The system MUST reuse compatible prepared runtime layers across
  tasks when doing so does not change the selected task's clean starting point.
- **FR-005**: During `prepare`, the system MUST stop before agent execution when
  a required runtime layer is missing unless the developer explicitly opted into
  creating missing runtime layers; `run` MUST NOT create missing runtime layers.
- **FR-006**: The system MUST verify the prepared task environment is tied to the
  selected task and starts from the selected base revision before any agent file
  operation occurs.
- **FR-006c**: `run` MUST consume only a ready prepared environment for the
  selected task; used, stopped, errored, missing, mismatched, or concurrently
  running prepared environments MUST fail before agent execution.
- **FR-006d**: `prepare` MUST reject an existing active entry for the same
  instance unless `--replace-existing` is supplied; with `--replace-existing`,
  it MUST stop or remove the prior prepared environment when present, replace
  only the active index entry, and leave prior run artifact directories intact.
- **FR-006e**: When `run` completes or exhausts limits without `--cleanup`, the
  active prepared environment index MUST retain the entry with status `used`.
  When `run --cleanup` is supplied, the run artifacts MUST record the
  `used -> stopped` transition, the container MUST be stopped or removed, and
  the active index entry MUST be removed.
- **FR-006f**: When a post-start runtime failure occurs with `--cleanup`, the
  run artifacts MUST record `running -> error` plus the cleanup action, the
  container MUST be stopped or removed when possible, and the active index entry
  MUST be removed.
- **FR-006a**: The first version MUST support two user-visible benchmark
  operations: prepare all required runtime and task environments, and run the
  agent from a prepared task environment.
- **FR-006b**: Batch benchmark orchestration MUST remain out of scope for this
  feature.
- **FR-007**: The system MUST keep model orchestration, budget tracking,
  trajectory writing, summary writing, prediction export, and final patch export
  outside the task workspace.
- **FR-008**: The system MUST keep repository reads, edits, searches, validation
  attempts, and final diff extraction confined to the selected task workspace.
- **FR-009**: The system MUST preserve the existing artifact contract for runs
  that reach agent execution and add runtime metadata needed to inspect the
  prepared environment.
- **FR-010**: The system MUST preserve partial diagnostic artifacts when runtime
  failures happen after agent execution starts.
- **FR-011**: The system MUST derive default validation from the selected task's
  fix-verification metadata.
- **FR-012**: The system MUST include regression validation only when the
  developer explicitly requests it on `run`.
- **FR-013**: The system MUST reject and record validation attempts outside the
  selected task's allowed validation set.
- **FR-014**: The system MUST prevent validation-only task files or patches from
  permanently contaminating the final code patch.
- **FR-015**: The system MUST perform final run review by executing the adapted
  TestSpec official-style `eval_script` inside the prepared environment, grade
  that script output, and report fixed checks, regression checks, failures, and
  unavailable validation sources separately.
- **FR-016**: The system MUST expose only `prepare` and `run` as user-visible
  SWE-Bench benchmark runtime operations for this feature.
- **FR-017**: The system MUST reject legacy SWE-Bench runtime operations,
  legacy sandbox registry options, and batch benchmark operations before agent
  execution.
- **FR-017a**: New benchmark `prepare` and `run` operations MUST NOT read from,
  write to, or fall back to the legacy sandbox registry.
- **FR-018**: The system MUST document each completed run as using the
  official-style runtime path.
- **FR-019**: The system MUST require implementation decisions for runtime
  behavior, validation behavior, and task metadata semantics to cite official
  documentation, official samples, upstream behavior, or existing project
  contracts before implementation begins.
- **FR-020**: The system MUST NOT satisfy requirements by branching on known
  test names, fixture-only task IDs, expected outputs, or undocumented lookup
  tables.
- **FR-021**: Any static mapping or fixture-like metadata required for supported
  tasks MUST be documented as domain metadata with its source and review status.

### Key Entities *(include if feature involves data)*

- **Benchmark Task**: A selected work item with identity, repository/version
  grouping, base revision, problem statement, validation metadata, optional
  regression metadata, and optional task patch metadata.
- **Runtime Lineage**: The recorded relationship between reusable preparation
  layers and the task-specific environment used for a run.
- **Prepared Task Environment**: The isolated workspace where repository reads,
  edits, searches, validation attempts, and final diff extraction happen for one
  selected task.
- **Agent Run**: One attempt to solve a selected task, including budgets, model
  interaction history, tool attempts, final outcome, and artifact locations.
- **Validation Set**: The allowed fix-verification and optional regression
  checks for the selected task.
- **Run Artifact Set**: The trajectory, summary, final patch, prediction output,
  and runtime metadata produced by a run.
- **Unsupported Legacy Operation**: A prior registry, sandbox, or batch
  SWE-Bench runtime entry point that this feature rejects instead of preserving
  as a compatibility path.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of supported benchmark tasks, runtime preparation either
  produces a ready task-specific environment or stops before agent execution
  with an actionable missing-prerequisite message.
- **SC-001a**: For 100% of benchmark tasks outside the supported repository
  set, the system stops before agent execution and reports that the repository
  is unsupported.
- **SC-001b**: For 100% of tasks missing source-backed metadata, the system
  stops before agent execution and reports which metadata source is missing.
- **SC-002**: For 100% of runs that reach agent execution, all repository file
  operations and validation attempts are confined to the selected task
  environment.
- **SC-002a**: A developer can complete both first-version operations against
  at least one supported benchmark task: prepare, then run.
- **SC-003**: For 100% of completed runs, the artifact set identifies the task,
  base revision, runtime lineage, validation source, selected validation mode,
  final outcome, and official-style runtime path used.
- **SC-004**: For 100% of runs using default validation, accepted validation
  attempts come only from the selected task's fix-verification metadata.
- **SC-005**: For 100% of runs with opt-in regression validation, regression
  results are reported separately from fix-verification results.
- **SC-006**: For 100% of runs that apply validation-only task files or patches,
  the final code patch excludes those validation-only changes.
- **SC-007**: A reviewer can inspect a completed or post-start failed run and
  determine within 3 minutes which runtime path, task metadata, validation
  source, prepared-environment status transition, and artifact locations were
  used from `summary.json` and `sandbox.json` without reading the active
  environment index or legacy registry.
- **SC-008**: 100% of SWE-Bench benchmark runtime CLI checks expose only
  `prepare` and `run` as supported operations.
- **SC-009**: New benchmark runs use the official-style runtime path in 100% of
  checks.
- **SC-009a**: 100% of new benchmark runtime checks reject legacy registry,
  legacy sandbox, and batch benchmark operations before agent execution.
- **SC-010**: Implementation review identifies zero undocumented static mappings,
  fixture-only branches, or expected-output shortcuts in the runtime refactor.

## Clarifications & Explicit Defaults

- The reference source for this specification is
  `docs/superpowers/plans/2026-06-17-official-swebench-sandbox.md`.
- The prior feature context is `specs/002-swebench-docker-sandbox`, and this
  feature is a refactor of the agent runtime environment flow rather than a
  request for unrelated benchmark orchestration.
- The first supported benchmark scope is the core SWE-Bench Lite repository set;
  repositories outside that set are unsupported for this feature.
- A core repository/version is supported only when required repository,
  environment, and validation metadata is source-backed; missing source-backed
  metadata makes that task unsupported for this feature.
- The first user-visible benchmark operations are `prepare` and `run` only.
  `prepare` resolves the task into an adapted TestSpec, prepares or reuses
  Base/Env/Instance image layers, and creates the task-specific prepared
  environment; `run` starts the agent from that prepared environment and does
  not build images.
- A prepared environment is single-use for solving: `run` accepts only a ready
  active entry, transitions it through running to used, and rejects used,
  stopped, errored, missing, mismatched, or concurrently running entries before
  agent execution.
- `run --cleanup` removes the consumed prepared environment from the active
  index after recording `used -> stopped` in run artifacts. Without
  `--cleanup`, the active index retains the consumed environment as `used`.
  If a post-start runtime failure occurs with `--cleanup`, artifacts record
  `running -> error` plus the cleanup action before the active index entry is
  removed.
- `prepare --replace-existing` is the only way to replace an active prepared
  environment for the same instance. Replacement updates the active index and
  prepared environment only; previous run artifact directories are not modified.
- Batch benchmark orchestration is out of scope for this feature.
- The default benchmark runtime path follows the reference plan's official-style
  environment preparation, task-specific environment creation, source-backed
  validation, and host-controlled agent solving model.
- No old SWE-Bench runtime operation is preserved as a compatibility path in
  this feature.
- New benchmark runs do not use the legacy sandbox registry.
- Creating missing runtime layers is opt-in; missing layers fail before agent
  execution by default.
- Regression validation is opt-in through `run --include-pass-to-pass`;
  fix-verification validation is the default.
- Agent-requested validation during a run may use only the selected task's
  allowed validation commands, while final review MUST execute the adapted
  TestSpec `eval_script` and use its graded output as the final benchmark
  outcome.
- Runtime implementation must be source-backed by official documentation,
  official samples, upstream behavior, or existing project contracts during
  planning.
- Static mappings are allowed only when documented as stable domain metadata,
  not as shortcuts for the current tests.
