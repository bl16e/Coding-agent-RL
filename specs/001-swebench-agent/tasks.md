# Tasks: SWE-Bench Lite Coding Agent

**Input**: Design documents from `specs/001-swebench-agent/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contract.md, quickstart.md

**Tests**: Included because the specification requires independently testable user stories and the plan selects pytest coverage.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on incomplete tasks.
- **[Story]**: User-story label for story phases only.
- Every task includes an exact target file path.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Initialize the Python package, CLI entrypoint, and test layout.

- [X] T001 Create Python packaging metadata with console script in pyproject.toml
- [X] T002 Create package initializer in src/coding_agent/__init__.py
- [X] T003 [P] Create CLI module skeleton in src/coding_agent/cli.py
- [X] T004 [P] Create pytest configuration and test path settings in pyproject.toml
- [X] T005 [P] Create unit, contract, integration test package markers in tests/unit/__init__.py, tests/contract/__init__.py, and tests/integration/__init__.py
- [X] T006 [P] Add development quick import smoke test in tests/unit/test_package_import.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared data types, workspace safety, budgets, model adapter, and artifact primitives required by every user story.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 Define core dataclasses and enums for BenchmarkTask, RunBudget, AgentRun, ToolCall, TrajectoryStep, TestResult, RunSummary, and Prediction in src/coding_agent/models.py
- [X] T008 Implement RunBudget validation and deadline helpers in src/coding_agent/budgets.py
- [X] T009 Implement workspace path containment and relative-path normalization in src/coding_agent/workspace.py
- [X] T010 [P] Define model backend protocol and AgentAction schema in src/coding_agent/model_backends/base.py
- [X] T011 [P] Implement deterministic mock backend for tests in src/coding_agent/model_backends/mock.py
- [X] T012 Implement model environment configuration loader for PROVIDER, MODEL, API_KEY, and BASE_URL in src/coding_agent/model_backends/openai_compatible.py
- [X] T013 Implement OpenAI-compatible request execution, timeout handling, and HTTP error mapping in src/coding_agent/model_backends/openai_compatible.py
- [X] T014 Implement OpenAI-compatible response parsing into AgentAction in src/coding_agent/model_backends/openai_compatible.py
- [X] T015 [P] Add unit tests for missing model environment variables in tests/unit/test_openai_compatible_config.py
- [X] T016 [P] Add unit tests for OpenAI-compatible response parsing and error mapping in tests/unit/test_openai_compatible_backend.py
- [X] T017 Implement JSONL trajectory writer with flush-after-step behavior in src/coding_agent/trajectory/writer.py
- [X] T018 Implement final patch generation from before-and-after workspace state in src/coding_agent/trajectory/patch.py
- [X] T019 Implement summary JSON writer in src/coding_agent/trajectory/summary.py
- [X] T020 Implement SWE-Bench prediction JSONL export in src/coding_agent/swebench/prediction.py
- [X] T021 [P] Add unit tests for budget validation and deadline behavior in tests/unit/test_budgets.py
- [X] T022 [P] Add unit tests for workspace containment and path rejection in tests/unit/test_workspace.py
- [X] T023 [P] Add unit tests for trajectory writer JSONL ordering and flush behavior in tests/unit/test_trajectory_writer.py
- [X] T024 [P] Add unit tests for final patch generation in tests/unit/test_patch.py
- [X] T025 [P] Add unit tests for SWE-Bench prediction schema in tests/unit/test_prediction.py
- [X] T026 Verify official SWE-Bench prediction fields are documented in specs/001-swebench-agent/research.md

**Checkpoint**: Foundation ready; user story implementation can start.

---

## Phase 3: User Story 1 - Run a Benchmark Task (Priority: P1) MVP

**Goal**: A developer can start one AgentRun for a prepared workspace and receive a terminal outcome plus required artifacts.

**Independent Test**: Run the CLI with the mock backend on a synthetic workspace and verify `trajectory.jsonl`, `final.patch`, `summary.json`, and `prediction.jsonl` exist with a final status.

### Tests for User Story 1

- [X] T027 [P] [US1] Add CLI run contract tests for required arguments and exit statuses in tests/contract/test_cli_run_contract.py
- [X] T028 [P] [US1] Add CLI run contract tests for missing task metadata and missing model environment variables in tests/contract/test_cli_run_invalid_config.py
- [X] T029 [P] [US1] Add AgentRun lifecycle tests for pending, running, terminal states in tests/unit/test_agent_run_lifecycle.py
- [X] T030 [P] [US1] Add integration test for mock backend end-to-end run artifacts in tests/integration/test_run_one_task.py
- [X] T031 [P] [US1] Add integration test that summary status, final.patch, and prediction model_patch are consistent in tests/integration/test_run_artifact_consistency.py
- [X] T032 [P] [US1] Add integration test for max-step and total-time budget stop summaries in tests/integration/test_run_budget_stop.py

### Implementation for User Story 1

- [X] T033 [US1] Implement `coding-agent run` argument parsing and validation in src/coding_agent/cli.py
- [X] T034 [US1] Implement AgentRun orchestration loop with model action dispatch in src/coding_agent/agent.py
- [X] T035 [US1] Implement run artifact directory creation and failure cleanup rules in src/coding_agent/agent.py
- [X] T036 [US1] Wire mock and OpenAI-compatible backend selection in src/coding_agent/cli.py
- [X] T037 [US1] Load root environment variables for OpenAI-compatible backend and fail invalid model configuration before AgentRun starts in src/coding_agent/cli.py
- [X] T038 [US1] Generate `trajectory.jsonl`, `final.patch`, `summary.json`, and `prediction.jsonl` at run completion in src/coding_agent/agent.py
- [X] T039 [US1] Record invalid task metadata and missing configuration diagnostics in src/coding_agent/trajectory/summary.py
- [X] T040 [US1] Record solved, failed, incomplete, and errored final outcomes in src/coding_agent/trajectory/summary.py
- [X] T041 [US1] Review cohesion of src/coding_agent/agent.py and split helper responsibilities if it exceeds orchestration scope

**Checkpoint**: User Story 1 is independently runnable with the mock backend.

---

## Phase 4: User Story 2 - Use the Required Tool Set (Priority: P2)

**Goal**: The agent can interact with the repository only through read_file, write_file, search_code, and run_tests with the specified safety constraints.

**Independent Test**: Run controlled tool calls and verify all file access stays inside the workspace, write_file uses complete-file content, and undeclared test commands are rejected and recorded.

### Tests for User Story 2

- [X] T042 [P] [US2] Add read_file tool tests for success, missing file, and outside-workspace rejection in tests/unit/test_tool_read_file.py
- [X] T043 [P] [US2] Add write_file tool tests for complete-file writes and outside-workspace rejection in tests/unit/test_tool_write_file.py
- [X] T044 [P] [US2] Add search_code tool tests for bounded matches, no matches, and max result behavior in tests/unit/test_tool_search_code.py
- [X] T045 [P] [US2] Add run_tests tool tests for allowed command execution, undeclared command rejection, and timeout in tests/unit/test_tool_run_tests.py
- [X] T046 [P] [US2] Add integration test proving all repository interactions are recorded as one of four tool types in tests/integration/test_tool_constraints.py

### Implementation for User Story 2

- [X] T047 [US2] Implement read_file tool in src/coding_agent/tools/read_file.py
- [X] T048 [US2] Implement write_file complete-content tool and modification tracking in src/coding_agent/tools/write_file.py
- [X] T049 [US2] Implement search_code bounded text search in src/coding_agent/tools/search_code.py
- [X] T050 [US2] Implement run_tests allowed-command enforcement and subprocess timeout in src/coding_agent/tools/run_tests.py
- [X] T051 [US2] Add tool registry and dispatch validation in src/coding_agent/tools/__init__.py
- [X] T052 [US2] Connect tool dispatch results to trajectory recording in src/coding_agent/agent.py
- [X] T053 [US2] Record rejected undeclared run_tests commands in src/coding_agent/trajectory/writer.py
- [X] T054 [US2] Review cohesion of src/coding_agent/tools/read_file.py, src/coding_agent/tools/write_file.py, src/coding_agent/tools/search_code.py, and src/coding_agent/tools/run_tests.py and keep each tool isolated from model backend concerns

**Checkpoint**: User Story 2 validates the constrained tool interface independently.

---

## Phase 5: User Story 3 - Review Complete Trajectory (Priority: P3)

**Goal**: A developer can inspect a completed run and understand ordered steps, decisions, tool calls, changes, tests, errors, and final outcome.

**Independent Test**: Complete a mock run and verify inspect/export commands show the outcome, last successful tool call, error point or budget stop, and SWE-Bench-compatible prediction.

### Tests for User Story 3

- [X] T055 [P] [US3] Add trajectory content tests for reasoning summary, next intent, and tool selection reason in tests/unit/test_trajectory_content.py
- [X] T056 [P] [US3] Add inspect CLI contract tests for missing run dir and report output in tests/contract/test_cli_inspect_contract.py
- [X] T057 [P] [US3] Add export-prediction CLI contract tests for JSONL output schema in tests/contract/test_cli_export_prediction_contract.py
- [X] T058 [P] [US3] Add integration test for errored run trajectory and summary diagnostics in tests/integration/test_errored_run_diagnostics.py

### Implementation for User Story 3

- [X] T059 [US3] Persist reasoning summary, next-step intent, and tool selection reason for every agent decision step in src/coding_agent/trajectory/writer.py
- [X] T060 [US3] Implement `coding-agent inspect` command in src/coding_agent/cli.py
- [X] T061 [US3] Implement inspect report rendering from summary and trajectory in src/coding_agent/trajectory/summary.py
- [X] T062 [US3] Implement `coding-agent export-prediction` command in src/coding_agent/cli.py
- [X] T063 [US3] Implement export-prediction file loading and writing in src/coding_agent/swebench/prediction.py
- [X] T064 [US3] Ensure trajectory persistence failures are surfaced with exit status 3 in src/coding_agent/agent.py
- [X] T065 [US3] Review cohesion of src/coding_agent/trajectory/writer.py, src/coding_agent/trajectory/patch.py, and src/coding_agent/trajectory/summary.py and keep inspect, summary, patch, and writer responsibilities separate

**Checkpoint**: All user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, quickstart validation, and maintainability checks across all stories.

- [X] T066 [P] Create or update README usage overview and MVP scope in README.md
- [X] T067 [P] Add quickstart command validation notes to specs/001-swebench-agent/quickstart.md
- [X] T068 Run full unit test suite with `python -m pytest tests/unit` and record result in specs/001-swebench-agent/quickstart.md
- [X] T069 Run contract test suite with `python -m pytest tests/contract` and record result in specs/001-swebench-agent/quickstart.md
- [X] T070 Run integration test suite with `python -m pytest tests/integration` and record result in specs/001-swebench-agent/quickstart.md
- [X] T071 Audit source files for oversized responsibilities and document any split in specs/001-swebench-agent/plan.md
- [X] T072 Verify generated prediction JSONL compatibility against contracts/cli-contract.md and update tests/contract/test_cli_export_prediction_contract.py if needed

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks every user story.
- **User Story 1 (Phase 3)**: Depends on Foundational and delivers MVP run capability.
- **User Story 2 (Phase 4)**: Depends on Foundational; can be built after or alongside US1, but final integration uses AgentRun wiring from US1.
- **User Story 3 (Phase 5)**: Depends on Foundational and artifact formats from US1; can develop inspect/export tests in parallel with US2 after US1 artifacts exist.
- **Polish (Phase 6)**: Depends on completed desired user stories.

### User Story Dependencies

- **US1 Run a Benchmark Task**: MVP; no dependency on US2/US3 beyond foundational interfaces.
- **US2 Use the Required Tool Set**: Depends on foundational tool dispatch; integrates with US1 agent loop.
- **US3 Review Complete Trajectory**: Depends on trajectory artifacts produced by US1 and enriched by US2 tool results.

### Within Each User Story

- Write tests before implementation tasks in the same story.
- Models and shared primitives are completed in Foundational before story work.
- Implement tool modules before wiring their results into the agent loop.
- Complete story checkpoint validation before moving to the next story for sequential delivery.

---

## Parallel Opportunities

- Setup tasks T003-T006 can run in parallel after T001-T002.
- Foundational backend and artifact tests T015-T016 and T021-T025 can run in parallel after their target modules are sketched.
- US1 tests T027-T032 can run in parallel before US1 implementation.
- US2 tool tests T042-T046 and tool implementations T047-T050 can be split by file.
- US3 tests T055-T058 can run in parallel before inspect/export implementation.
- Polish documentation tasks T066-T067 can run in parallel with final validation.

## Parallel Example: User Story 2

```text
Task: "T042 [P] [US2] Add read_file tool tests for success, missing file, and outside-workspace rejection in tests/unit/test_tool_read_file.py"
Task: "T043 [P] [US2] Add write_file tool tests for complete-file writes and outside-workspace rejection in tests/unit/test_tool_write_file.py"
Task: "T044 [P] [US2] Add search_code tool tests for bounded matches, no matches, and max result behavior in tests/unit/test_tool_search_code.py"
Task: "T045 [P] [US2] Add run_tests tool tests for allowed command execution, undeclared command rejection, and timeout in tests/unit/test_tool_run_tests.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 Setup.
2. Complete Phase 2 Foundational.
3. Complete Phase 3 User Story 1.
4. Validate the mock backend end-to-end run produces all four artifacts.

### Incremental Delivery

1. Deliver US1 for runnable single-task MVP.
2. Add US2 to enforce the exact four-tool repository interface.
3. Add US3 for full review, inspect, and prediction export workflows.
4. Run Phase 6 validation and quickstart checks.

### Team Parallel Strategy

After Foundational:
- Developer A: US1 agent loop and run CLI.
- Developer B: US2 tools and safety tests.
- Developer C: US3 trajectory inspection and export commands.

---

## Notes

- All task IDs are sequential and executable in dependency order.
- `[P]` tasks touch separate files or independent test modules.
- User story tasks include `[US1]`, `[US2]`, or `[US3]` labels.
- Every implementation task includes a concrete file path.
- Optional after-tasks hook available: `/speckit-git-commit`.
