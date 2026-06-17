# Feature Specification: Agent Runtime Environment Refactor

**Feature Branch**: `003-agent-runtime-refactor`

**Created**: 2026-06-17

**Status**: Draft

**Input**: User description: "参考docs/superpowers/plans/2026-06-17-official-swebench-sandbox.md 这个文档对我当前项目的agent 运行环境部分 的整体流程和做法 进行重构"

## Clarifications

### Session 2026-06-17

- Q: What is the first supported benchmark task scope for this refactor? → A: Core SWE-Bench Lite repository set; unknown repositories fail with an explicit unsupported message.
- Q: How should a core repository/version be handled when source-backed metadata is unavailable? → A: Treat it as unsupported and fail before agent execution with a missing source-backed metadata message.
- Q: What legacy sandbox registry compatibility level is required? → A: Keep only explicit legacy commands and flows compatible; new benchmark runs do not use the legacy registry.
- Q: Which user-visible operation modes are required in the first version? → A: Prepare runtime, run directly, and continue a prepared environment; batch benchmark orchestration is out of scope.

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

A developer wants to either run a benchmark task directly or continue from a
prepared task environment while preserving the existing run artifacts, budgets,
model interaction flow, and repository-tool behavior.

**Why this priority**: The refactor must improve runtime preparation without
breaking the agent's core solving workflow or existing artifact contract.

**Independent Test**: Can be tested by running one task directly, preparing one
task and continuing it, and confirming that code inspection, edits, search, and
allowed validation occur only in the selected environment while trajectory,
summary, final patch, and prediction artifacts remain available to the
developer.

**Acceptance Scenarios**:

1. **Given** a prepared task environment, **When** the developer starts an agent
   run, **Then** the agent operates only on the selected task workspace.
2. **Given** a selected task has not already been prepared, **When** the
   developer starts a direct run, **Then** the system prepares the task
   environment and starts the agent in one workflow.
3. **Given** the agent completes or exhausts its configured limits, **When** the
   run ends, **Then** the developer receives the same core artifact set as the
   current project flow plus environment metadata.
4. **Given** an environment failure occurs after the run has started, **When**
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

### User Story 4 - Migrate Without Breaking Existing Workflows (Priority: P4)

A developer wants the refactor to make the official-style runtime path the
default for benchmark tasks while keeping existing prepared-workspace and legacy
sandbox workflows usable during migration.

**Why this priority**: The project already has working flows and artifacts.
Migration must be deliberate, observable, and reversible enough for current
users to continue work.

**Independent Test**: Can be tested by running an existing prepared-workspace
task and a legacy sandbox registration flow after the refactor and confirming
that both remain available while new benchmark runs use the official-style
runtime path by default.

**Acceptance Scenarios**:

1. **Given** a developer uses the existing prepared-workspace run flow, **When**
   the refactor is present, **Then** that flow continues to run without requiring
   benchmark environment configuration.
2. **Given** a developer has legacy sandbox metadata, **When** they use a
   compatibility path, **Then** the system identifies it as compatibility
   behavior and preserves required validation safeguards.
3. **Given** a new benchmark task run is started, **When** no compatibility path
   is explicitly selected, **Then** the official-style runtime path is used.

### Edge Cases

- Selected task metadata is missing, malformed, or incomplete.
- The referenced official behavior or sample is ambiguous for a supported task.
- A required runtime layer is missing and the developer did not opt into
  creating missing layers.
- Runtime preparation starts but fails before the agent begins.
- Runtime preparation succeeds but readiness checks show an incorrect task
  identity, dirty workspace, or wrong base revision.
- Agent work starts and the runtime environment later fails.
- Validation metadata is unavailable, empty, or cannot be translated into
  allowed validation attempts.
- Validation introduces task test files that must be removed or reset after the
  validation attempt.
- A compatibility path conflicts with the new default runtime path.
- Existing run artifacts are present when a new task run starts.
- A developer attempts batch benchmark orchestration in this feature scope.
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
- **FR-005**: The system MUST stop before agent execution when a required
  runtime layer is missing unless the developer explicitly opted into creating
  missing runtime layers.
- **FR-006**: The system MUST verify the prepared task environment is tied to the
  selected task and starts from the selected base revision before any agent file
  operation occurs.
- **FR-006a**: The first version MUST support three user-visible benchmark
  operation modes: prepare a runtime environment, run a selected task directly,
  and continue solving from a prepared environment.
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
  developer explicitly requests it.
- **FR-013**: The system MUST reject and record validation attempts outside the
  selected task's allowed validation set.
- **FR-014**: The system MUST prevent validation-only task files or patches from
  permanently contaminating the final code patch.
- **FR-015**: The system MUST report final validation outcomes in a way that
  distinguishes fixed checks, regression checks, failures, and unavailable
  validation sources.
- **FR-016**: The system MUST keep existing prepared-workspace runs available
  without requiring benchmark runtime configuration.
- **FR-017**: The system MUST keep legacy sandbox registry behavior available as
  an explicit compatibility path until it is intentionally removed by a later
  feature.
- **FR-017a**: New benchmark runs MUST NOT use the legacy sandbox registry path;
  legacy registry behavior is available only through explicit legacy commands
  or compatibility flows.
- **FR-018**: The system MUST document whether each completed run used the new
  default runtime path or a compatibility path.
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
- **Compatibility Path**: An explicitly selected legacy workflow that remains
  usable while the new default benchmark runtime workflow is introduced.

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
- **SC-002a**: A developer can complete each first-version operation mode
  against at least one supported benchmark task: prepare runtime, direct run,
  and continue prepared environment.
- **SC-003**: For 100% of completed runs, the artifact set identifies the task,
  base revision, runtime lineage, validation source, selected validation mode,
  final outcome, and compatibility/default path used.
- **SC-004**: For 100% of runs using default validation, accepted validation
  attempts come only from the selected task's fix-verification metadata.
- **SC-005**: For 100% of runs with opt-in regression validation, regression
  results are reported separately from fix-verification results.
- **SC-006**: For 100% of runs that apply validation-only task files or patches,
  the final code patch excludes those validation-only changes.
- **SC-007**: A reviewer can inspect a completed or post-start failed run and
  determine within 3 minutes which runtime path, task metadata, validation
  source, and artifact locations were used.
- **SC-008**: Existing prepared-workspace runs continue to complete with no
  benchmark runtime configuration in 100% of compatibility checks.
- **SC-009**: New benchmark runs use the official-style runtime path by default
  in 100% of checks unless a compatibility path is explicitly selected.
- **SC-009a**: 100% of new benchmark run checks avoid the legacy registry path
  unless the developer invoked an explicit legacy compatibility flow.
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
- The first user-visible operation modes are prepare runtime, direct run, and
  continue prepared environment.
- Batch benchmark orchestration is out of scope for this feature.
- The default benchmark runtime path follows the reference plan's official-style
  environment preparation, task-specific environment creation, source-backed
  validation, and host-controlled agent solving model.
- The existing prepared-workspace flow remains supported.
- Legacy sandbox registry behavior remains available only as an explicit
  compatibility path.
- New benchmark runs do not use the legacy sandbox registry; legacy registry
  behavior is limited to explicit legacy commands and compatibility flows.
- Creating missing runtime layers is opt-in; missing layers fail before agent
  execution by default.
- Regression validation is opt-in; fix-verification validation is the default.
- Runtime implementation must be source-backed by official documentation,
  official samples, upstream behavior, or existing project contracts during
  planning.
- Static mappings are allowed only when documented as stable domain metadata,
  not as shortcuts for the current tests.
