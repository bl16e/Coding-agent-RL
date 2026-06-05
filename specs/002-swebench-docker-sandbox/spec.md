# Feature Specification: SWE-Bench Docker Sandbox

**Feature Branch**: `002-swebench-docker-sandbox`

**Created**: 2026-06-05

**Status**: Draft

**Input**: User description: "Add a SWE-Bench task runtime environment that uses Docker containers as sandboxes. After several reusable base sandboxes are configured, the coding agent can operate inside them to modify code and run tests."

## Clarifications

### Session 2026-06-05

- Q: Should base sandboxes target official SWE-Bench-compatible environments or the lightweight local Dockerfiles? -> A: Official SWE-Bench-compatible environments are the target; local Dockerfiles may be used only as supporting reference or cache ideas.
- Q: Where should the agent process run during sandboxed tasks? -> A: The agent runs on the host and operates on task containers through Docker; containers hold only task code and test execution.
- Q: How should task sandboxes be handled between runs? -> A: Preserve run artifacts; reusable sandboxes may be reused for later tasks, but each new run must reset to the selected task's correct base commit before agent actions begin.
- Q: What should happen when a required base sandbox is missing? -> A: The task run fails before agent execution and prompts the developer to configure the required base sandbox; it does not auto-create the sandbox.
- Q: Should PASS_TO_PASS regression tests be included in the default allowed validation set? -> A: Default validation includes only FAIL_TO_PASS; PASS_TO_PASS is included only when explicitly requested by the developer.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a Task in a Sandbox (Priority: P1)

A developer selects a SWE-Bench Lite task from the local dataset and starts an agent run in an isolated task environment so the agent can inspect code, modify files, run validation tests, and produce run artifacts without requiring the target repository to be prepared manually on the host machine.

**Why this priority**: This is the core value of the feature. The existing agent can run only against a prepared local workspace; real SWE-Bench Lite usage requires repeatable task environments.

**Independent Test**: Can be tested by selecting one known SWE-Bench Lite development task, preparing its sandbox, running the agent, and verifying that code changes, test attempts, trajectory, summary, and final patch are produced for that task.

**Acceptance Scenarios**:

1. **Given** a local SWE-Bench Lite task with repository metadata and problem statement, **When** the developer starts a sandboxed run, **Then** the system prepares the task code at the task's base revision and starts the agent inside the isolated task environment.
2. **Given** a sandboxed run is active, **When** the agent reads files, writes files, searches code, or runs tests, **Then** those operations affect only the selected task environment and are recorded in the run trajectory.
3. **Given** the agent finishes or reaches a configured limit, **When** the run ends, **Then** the developer receives the final patch, prediction record, summary, and complete trajectory for the sandboxed task.
4. **Given** a sandboxed run is active, **When** the agent decides on the next action, **Then** model access and artifact persistence are handled outside the task sandbox while code and test operations occur inside the selected task container.

---

### User Story 2 - Reuse Prepared Base Sandboxes (Priority: P2)

A developer configures a small set of reusable base sandboxes for repositories represented in SWE-Bench Lite so repeated task runs can start from those bases instead of rebuilding a full environment for every task.

**Why this priority**: SWE-Bench Lite contains many tasks across a smaller number of repositories. Reusing base environments reduces setup time and makes repeated evaluation practical.

**Independent Test**: Can be tested by preparing a base sandbox for one repository, running two different tasks from that repository, and verifying that each task starts from its own base revision while sharing the prepared base environment.

**Acceptance Scenarios**:

1. **Given** a repository appears in the SWE-Bench Lite dataset, **When** the developer requests a reusable base sandbox for that repository, **Then** the system records that the base sandbox is available for compatible tasks.
2. **Given** a compatible base sandbox exists, **When** the developer starts a task from the same repository, **Then** the task run uses the existing base sandbox and resets to the selected task's base revision before agent actions begin.
3. **Given** a base sandbox is missing or unusable, **When** the developer starts a task requiring it, **Then** the system reports the missing or unusable sandbox before starting the agent.
4. **Given** a reusable sandbox previously ran another task, **When** a new task starts, **Then** the system preserves prior run artifacts outside the task workspace and resets the task workspace to the new task's base revision.
5. **Given** no compatible base sandbox exists for a selected task, **When** the developer starts that task, **Then** the system fails before agent execution and tells the developer which base sandbox must be configured.

---

### User Story 3 - Validate Against SWE-Bench Test Metadata (Priority: P3)

A developer wants test execution for sandboxed tasks to follow the validation context provided by SWE-Bench Lite so each run can check tests expected to fail before the fix and pass afterward, while preserving regression coverage where available.

**Why this priority**: Real benchmark runs require test commands to be tied to the selected task's validation metadata, not arbitrary manual commands.

**Independent Test**: Can be tested by selecting a task with validation test metadata, running the agent, and confirming that allowed test execution is derived from that task's validation context and recorded in the trajectory.

**Acceptance Scenarios**:

1. **Given** a selected SWE-Bench Lite task contains validation test identifiers, **When** a sandboxed run is configured, **Then** the allowed test set for the run includes the task's expected fix-verification tests.
2. **Given** the task also contains regression test identifiers, **When** validation is configured with regression tests explicitly enabled, **Then** the developer can include those regression tests in the allowed validation set for the run.
3. **Given** the agent requests a test outside the allowed validation set, **When** the request is made, **Then** the system rejects and records the rejected test request.

### Edge Cases

- The local SWE-Bench Lite dataset file is missing, unreadable, or lacks required task fields.
- A selected task references a repository or base revision that cannot be prepared.
- A reusable base sandbox exists but is stale, corrupted, or incompatible with the selected task.
- A selected task requires a base sandbox that has not been configured.
- A task run starts from a dirty sandbox state left by a previous run.
- Prior run artifacts exist while the reusable sandbox is reset for a new task.
- Sandbox setup completes but the repository dependency setup fails.
- The agent attempts to read, write, search, or test outside the selected task environment.
- The selected task has no validation test metadata or the metadata cannot be translated into allowed test commands.
- Tests fail, time out, or cannot be executed inside the sandbox.
- Final patch extraction fails after the agent has modified files.
- Trajectory persistence fails during a sandboxed run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow a developer to select a SWE-Bench Lite task from the local dataset by task identity.
- **FR-002**: The system MUST validate that a selected task includes the repository identity, base revision, problem statement, and validation context required for a sandboxed run.
- **FR-003**: The system MUST allow a developer to prepare reusable base sandboxes for repositories represented in the SWE-Bench Lite dataset.
- **FR-003a**: The system MUST treat official SWE-Bench-compatible environment behavior as the target for base sandbox preparation and task validation.
- **FR-004**: The system MUST allow a sandboxed task run to reuse a compatible prepared base sandbox for the task's repository.
- **FR-004a**: The system MUST NOT automatically create a missing base sandbox during task execution.
- **FR-005**: The system MUST reset each task run to the selected task's base revision before the agent performs any code operation.
- **FR-005a**: The system MUST preserve completed run artifacts independently from sandbox workspace reset or reuse.
- **FR-006**: The system MUST keep every agent file operation and test operation confined to the selected task's sandboxed environment.
- **FR-007**: The system MUST expose the existing agent tools to sandboxed task runs: read_file, write_file, search_code, and run_tests.
- **FR-007a**: The system MUST run the agent control process outside the task sandbox while executing repository tools against the selected task container.
- **FR-008**: The system MUST ensure write_file changes are reflected in the sandboxed task code and included in the final patch for that run.
- **FR-009**: The system MUST ensure run_tests executes only test commands allowed for the selected sandboxed task.
- **FR-010**: The system MUST derive default allowed validation tests from the selected SWE-Bench Lite task's fix-verification metadata.
- **FR-010a**: The system MUST NOT include regression test metadata in the default allowed validation set.
- **FR-011**: The system MUST allow regression test metadata from the selected task to be included in the allowed validation set when explicitly requested by the developer.
- **FR-012**: The system MUST reject and record any agent request that attempts to execute a test outside the allowed validation set.
- **FR-013**: The system MUST preserve the complete trajectory, final patch, summary, and prediction record for every sandboxed run that reaches agent execution.
- **FR-014**: The system MUST report sandbox preparation failures before agent execution begins.
- **FR-014a**: The system MUST identify the required base sandbox when a selected task cannot run because that base sandbox is missing.
- **FR-015**: The system MUST report sandbox runtime failures in the run summary and trajectory when they occur after agent execution begins.
- **FR-016**: The system MUST prevent one task run from inheriting file changes made by a previous task run.
- **FR-016a**: The system MUST clean or reset reusable sandbox workspaces before a later task starts while keeping previous run artifacts available for inspection.
- **FR-017**: The system MUST let a developer inspect which base sandbox and task revision were used for a completed sandboxed run.
- **FR-018**: The system MUST keep the existing single-task run behavior available for prepared local workspaces.

### Key Entities *(include if feature involves data)*

- **SWE-Bench Task Record**: A local dataset entry containing task identity, repository identity, base revision, problem statement, validation tests, and optional regression tests.
- **Base Sandbox**: A reusable prepared repository environment that can be used as the starting point for multiple task runs from the same repository.
- **Task Sandbox**: An isolated per-run task environment reset to a selected task's base revision before agent actions begin.
- **Sandboxed Agent Run**: One attempt to solve a selected task inside a task sandbox, including selected task metadata, base sandbox identity, run limits, final outcome, and artifacts.
- **Host Agent Controller**: The agent control process that manages model access, trajectory persistence, and tool requests while directing repository operations to a selected task sandbox.
- **Validation Test Set**: The allowed tests derived from the selected task's validation metadata and any developer-selected regression tests.
- **Sandbox Artifact Set**: The trajectory, final patch, summary, prediction record, and sandbox metadata produced by a sandboxed run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can start a sandboxed run for one selected SWE-Bench Lite development task and receive a final outcome and artifacts in 100% of runs that reach agent execution.
- **SC-002**: For every sandboxed run, 100% of agent file and test operations are confined to the selected task environment.
- **SC-003**: For every sandboxed run that modifies code, 100% of final patch content is derived from changes made in that run's task environment.
- **SC-004**: For every sandboxed run with validation tests, 100% of accepted test attempts are part of the selected task's allowed validation set.
- **SC-004a**: For every sandboxed run using default validation, 100% of accepted validation tests come from the selected task's fix-verification metadata.
- **SC-005**: A developer can prepare a reusable base sandbox for a repository and use it for at least two different tasks from that repository without rebuilding the base environment.
- **SC-005a**: When a reusable sandbox is used for consecutive tasks, 100% of later runs start from the selected task's base revision rather than prior run modifications.
- **SC-006**: A reviewer can identify the selected task, repository, base revision, base sandbox, final outcome, and validation test results from run artifacts in under 3 minutes.
- **SC-007**: Missing dataset metadata, missing base sandbox, sandbox setup failure, and sandbox runtime failure are reported with actionable messages in 100% of affected attempts.
- **SC-007a**: 100% of attempts with missing base sandboxes stop before agent execution and identify the sandbox that must be configured.
- **SC-008**: Existing prepared-workspace single-task runs continue to work with no additional sandbox configuration.

## Clarifications & Explicit Defaults

- This feature extends the existing single-task coding agent with sandboxed SWE-Bench Lite task execution.
- Docker container sandboxes are the user-selected isolation mechanism for this feature.
- Base sandbox behavior targets official SWE-Bench-compatible task environments; local Dockerfile examples may inform caching or setup but do not define the required benchmark behavior.
- The agent control process runs on the host; task containers are responsible for repository state and test execution only.
- The initial scope covers one selected SWE-Bench Lite task per agent run; full benchmark batch orchestration remains out of scope unless specified separately.
- Reusable base sandboxes are prepared per repository, and each task run starts from the selected task's base revision.
- Missing base sandboxes are treated as pre-run configuration errors rather than automatically created during task execution.
- The existing four-tool agent contract remains unchanged: read_file, write_file, search_code, and run_tests.
- Default validation includes FAIL_TO_PASS test metadata only; PASS_TO_PASS regression metadata is opt-in.
- The existing trajectory, final patch, summary, and prediction artifact expectations remain unchanged for sandboxed runs.
- A sandboxed run must not mutate the reusable base sandbox in a way that affects later task runs.
- Completed run artifacts are retained outside the reusable sandbox workspace so later workspace resets do not remove inspection data.
- The existing prepared-local-workspace flow remains supported.
