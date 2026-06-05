# Tasks: SWE-Bench Docker Sandbox

**Input**: Design documents from `specs/002-swebench-docker-sandbox/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contract.md, quickstart.md

**Tests**: Include pytest unit, contract, and integration tests because this feature changes CLI behavior, Docker command boundaries, dataset parsing, and run artifacts.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files or has no dependency on incomplete tasks.
- **[Story]**: User story label for story phases only.
- Every task includes an exact repository path.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add package/development scaffolding needed by all sandbox work.

- [ ] T001 Add `pyarrow` runtime dependency and keep pytest dev dependency in `pyproject.toml`
- [ ] T002 [P] Create sandbox package marker in `src/coding_agent/sandbox/__init__.py`
- [ ] T003 [P] Create Docker CLI wrapper module skeleton in `src/coding_agent/sandbox/docker_cli.py`
- [ ] T004 [P] Create sandbox registry module skeleton in `src/coding_agent/sandbox/registry.py`
- [ ] T005 [P] Create sandbox manager module skeleton in `src/coding_agent/sandbox/manager.py`
- [ ] T006 [P] Create container tools module skeleton in `src/coding_agent/sandbox/tools.py`
- [ ] T007 [P] Create SWE-Bench dataset module skeleton in `src/coding_agent/swebench/dataset.py`
- [ ] T008 [P] Create SWE-Bench validation module skeleton in `src/coding_agent/swebench/validation.py`
- [ ] T009 [P] Create sandboxed run orchestration module skeleton in `src/coding_agent/swebench/sandbox_run.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared contracts and infrastructure that must exist before story implementation.

**CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T010 [P] Add sandbox-related dataclasses to `src/coding_agent/models.py`
- [ ] T011 [P] Add `ToolExecutor` protocol and `LocalToolExecutor` in `src/coding_agent/tools/executor.py`
- [ ] T012 Refactor `run_task` to accept a `ToolExecutor` while preserving local behavior in `src/coding_agent/agent.py`
- [ ] T013 Update local tool dispatch wiring to use `LocalToolExecutor` in `src/coding_agent/tools/__init__.py`
- [ ] T014 Add sandbox metadata fields to run summary serialization in `src/coding_agent/models.py`
- [ ] T015 [P] Add unit tests for `ToolExecutor` local compatibility in `tests/unit/test_tool_executor.py`
- [ ] T016 [P] Add regression integration test that existing `coding-agent run` still works in `tests/integration/test_prepared_workspace_compatibility.py`
- [ ] T017 [P] Add Docker CLI fake helpers for unit tests in `tests/unit/fakes/docker_cli.py`
- [ ] T018 [P] Add repository file responsibility notes for new sandbox modules in `specs/002-swebench-docker-sandbox/plan.md`

**Checkpoint**: Foundation ready. Existing prepared-workspace run still passes and user story work can begin.

---

## Phase 3: User Story 1 - Run a Task in a Sandbox (Priority: P1) MVP

**Goal**: A developer can run one selected SWE-Bench Lite task in a configured Docker sandbox and receive standard artifacts plus sandbox metadata.

**Independent Test**: Select one dataset instance with a registered sandbox image, run `coding-agent swebench run`, and verify workspace reset, container tool execution, trajectory, final patch, summary, prediction, and `sandbox.json`.

### Tests for User Story 1

- [ ] T019 [P] [US1] Add CLI contract test for `coding-agent swebench run` required arguments in `tests/contract/test_cli_swebench_run_contract.py`
- [ ] T020 [P] [US1] Add CLI contract test for missing dataset and missing instance failures in `tests/contract/test_cli_swebench_run_contract.py`
- [ ] T021 [P] [US1] Add unit tests for parquet task loading and required field validation in `tests/unit/test_swebench_dataset.py`
- [ ] T022 [P] [US1] Add unit tests for Docker command wrapper success, failure, and timeout mapping in `tests/unit/test_docker_cli.py`
- [ ] T023 [P] [US1] Add unit tests for task sandbox reset to base commit in `tests/unit/test_sandbox_manager.py`
- [ ] T024 [P] [US1] Add unit tests for container-backed read/write/search tools in `tests/unit/test_container_tools.py`
- [ ] T025 [P] [US1] Add integration test with fake Docker for sandboxed run artifacts in `tests/integration/test_swebench_sandbox_run.py`

### Implementation for User Story 1

- [ ] T026 [US1] Implement local parquet row lookup by `instance_id` in `src/coding_agent/swebench/dataset.py`
- [ ] T027 [US1] Implement `SwebenchTaskRecord` validation helpers in `src/coding_agent/swebench/dataset.py`
- [ ] T028 [US1] Implement bounded Docker CLI command execution in `src/coding_agent/sandbox/docker_cli.py`
- [ ] T029 [US1] Implement Docker image/container inspect helpers in `src/coding_agent/sandbox/docker_cli.py`
- [ ] T030 [US1] Implement task container creation/start/stop lifecycle in `src/coding_agent/sandbox/manager.py`
- [ ] T031 [US1] Implement workspace reset to task `base_commit` before agent execution in `src/coding_agent/sandbox/manager.py`
- [ ] T032 [US1] Implement container-backed `read_file` in `src/coding_agent/sandbox/tools.py`
- [ ] T033 [US1] Implement container-backed `write_file` with complete-file semantics in `src/coding_agent/sandbox/tools.py`
- [ ] T034 [US1] Implement container-backed `search_code` with bounded result output in `src/coding_agent/sandbox/tools.py`
- [ ] T035 [US1] Implement container-backed `run_tests` with allowed-command enforcement in `src/coding_agent/sandbox/tools.py`
- [ ] T036 [US1] Implement `ContainerToolExecutor` that adapts container tools to `ToolExecutor` in `src/coding_agent/sandbox/tools.py`
- [ ] T037 [US1] Implement sandboxed single-task orchestration in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T038 [US1] Write `sandbox.json` artifact with task, repo, base commit, image, repo path, and validation mode in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T039 [US1] Add `coding-agent swebench run` parser and command handler in `src/coding_agent/cli.py`
- [ ] T040 [US1] Map invalid sandboxed run inputs to exit status 2 and runtime failures to exit status 4 in `src/coding_agent/cli.py`
- [ ] T041 [US1] Ensure `summary.json` includes sandbox metadata for sandboxed runs in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T042 [US1] Review cohesion of `src/coding_agent/agent.py` after executor injection and split if responsibilities grow in `specs/002-swebench-docker-sandbox/plan.md`

**Checkpoint**: User Story 1 is independently runnable with fake Docker and produces all sandbox artifacts.

---

## Phase 4: User Story 2 - Reuse Prepared Base Sandboxes (Priority: P2)

**Goal**: A developer can register prepared base sandbox images, list them, and run multiple tasks from the same repository while each run resets to its selected base commit.

**Independent Test**: Register one image for a repository, run two different task records from that repository with fake Docker, and verify both use the registered image while resetting to their own base commits.

### Tests for User Story 2

- [ ] T043 [P] [US2] Add CLI contract tests for `coding-agent sandbox register` in `tests/contract/test_cli_sandbox_contract.py`
- [ ] T044 [P] [US2] Add CLI contract tests for `coding-agent sandbox list` in `tests/contract/test_cli_sandbox_contract.py`
- [ ] T045 [P] [US2] Add unit tests for registry save/load/update behavior in `tests/unit/test_sandbox_registry.py`
- [ ] T046 [P] [US2] Add unit tests for missing image and missing registry errors in `tests/unit/test_sandbox_registry.py`
- [ ] T047 [P] [US2] Add integration test that missing base sandbox fails before model execution in `tests/integration/test_sandbox_registry_integration.py`
- [ ] T048 [P] [US2] Add integration test that reusable sandbox resets between two task runs in `tests/integration/test_sandbox_reuse.py`

### Implementation for User Story 2

- [ ] T049 [US2] Implement `BaseSandbox` registry JSON load and save in `src/coding_agent/sandbox/registry.py`
- [ ] T050 [US2] Implement Docker image existence validation during registration in `src/coding_agent/sandbox/registry.py`
- [ ] T051 [US2] Implement lookup by repository and missing-base-sandbox error in `src/coding_agent/sandbox/registry.py`
- [ ] T052 [US2] Implement `coding-agent sandbox register` parser and command handler in `src/coding_agent/cli.py`
- [ ] T053 [US2] Implement `coding-agent sandbox list` parser and command handler in `src/coding_agent/cli.py`
- [ ] T054 [US2] Connect `coding-agent swebench run` to registry lookup and pre-model missing sandbox failure in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T055 [US2] Persist prior run artifacts outside sandbox workspace reset paths in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T056 [US2] Document reusable sandbox registration workflow in `specs/002-swebench-docker-sandbox/quickstart.md`

**Checkpoint**: User Stories 1 and 2 work independently; missing base sandbox never starts the agent.

---

## Phase 5: User Story 3 - Validate Against SWE-Bench Test Metadata (Priority: P3)

**Goal**: Sandboxed runs derive allowed tests from SWE-Bench metadata, default to `FAIL_TO_PASS`, and include `PASS_TO_PASS` only when explicitly requested.

**Independent Test**: Load a task with both validation lists, run once without `--include-pass-to-pass` and once with it, and verify accepted test commands match the expected allowed set.

### Tests for User Story 3

- [ ] T057 [P] [US3] Add unit tests for parsing `FAIL_TO_PASS` and `PASS_TO_PASS` metadata in `tests/unit/test_swebench_validation.py`
- [ ] T058 [P] [US3] Add unit tests for default validation excluding `PASS_TO_PASS` in `tests/unit/test_swebench_validation.py`
- [ ] T059 [P] [US3] Add unit tests for `--include-pass-to-pass` including regression tests in `tests/unit/test_swebench_validation.py`
- [ ] T060 [P] [US3] Add contract test for `--include-pass-to-pass` CLI behavior in `tests/contract/test_cli_swebench_run_contract.py`
- [ ] T061 [P] [US3] Add integration test for rejecting container test commands outside the allowed set in `tests/integration/test_swebench_validation_integration.py`

### Implementation for User Story 3

- [ ] T062 [US3] Implement JSON/list normalization for `FAIL_TO_PASS` and `PASS_TO_PASS` in `src/coding_agent/swebench/validation.py`
- [ ] T063 [US3] Implement default `ValidationTestSet` construction from `FAIL_TO_PASS` in `src/coding_agent/swebench/validation.py`
- [ ] T064 [US3] Implement opt-in `PASS_TO_PASS` inclusion in `src/coding_agent/swebench/validation.py`
- [ ] T065 [US3] Convert validation test identifiers into exact allowed test commands in `src/coding_agent/swebench/validation.py`
- [ ] T066 [US3] Wire `--include-pass-to-pass` into `coding-agent swebench run` in `src/coding_agent/cli.py`
- [ ] T067 [US3] Record validation mode and allowed test counts in `sandbox.json` and `summary.json` in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T068 [US3] Ensure rejected undeclared container test commands are recorded in trajectory in `src/coding_agent/sandbox/tools.py`

**Checkpoint**: All user stories are independently functional and validation metadata controls test execution.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, verification, and responsibility review across the completed feature.

- [ ] T069 [P] Update root `README.md` with sandbox command summary and prepared-workspace compatibility note
- [ ] T070 [P] Add sandbox quickstart validation notes to `specs/002-swebench-docker-sandbox/quickstart.md`
- [ ] T071 Run unit tests with `python -m pytest tests/unit` and record results in `specs/002-swebench-docker-sandbox/quickstart.md`
- [ ] T072 Run contract tests with `python -m pytest tests/contract` and record results in `specs/002-swebench-docker-sandbox/quickstart.md`
- [ ] T073 Run integration tests with `python -m pytest tests/integration` and record results in `specs/002-swebench-docker-sandbox/quickstart.md`
- [ ] T074 Run full test suite with `python -m pytest tests` and record results in `specs/002-swebench-docker-sandbox/quickstart.md`
- [ ] T075 Audit `src/coding_agent/cli.py`, `src/coding_agent/agent.py`, `src/coding_agent/models.py`, `src/coding_agent/sandbox/`, and `src/coding_agent/swebench/` for oversized responsibilities and document split decisions in `specs/002-swebench-docker-sandbox/plan.md`
- [ ] T076 Verify CLI contracts against `specs/002-swebench-docker-sandbox/contracts/cli-contract.md`
- [ ] T077 Verify official SWE-Bench and Docker source assumptions remain documented in `specs/002-swebench-docker-sandbox/research.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational and delivers the MVP sandboxed run.
- **User Story 2 (Phase 4)**: Depends on Foundational; can be implemented after or alongside US1, but end-to-end reuse validation benefits from US1 orchestration.
- **User Story 3 (Phase 5)**: Depends on Foundational; can be implemented after validation module setup, but full integration benefits from US1 orchestration.
- **Polish (Phase 6)**: Depends on completed desired user stories.

### User Story Dependencies

- **US1 Run a Task in a Sandbox**: MVP; no dependency on US2 or US3 beyond foundational registry interfaces and validation defaults.
- **US2 Reuse Prepared Base Sandboxes**: Independent registration/listing is testable without US1; two-run reuse integration depends on US1 orchestration.
- **US3 Validate Against SWE-Bench Test Metadata**: Unit-testable independently; full command behavior depends on US1 CLI and sandboxed run wiring.

### Parallel Opportunities

- Setup skeleton tasks T002-T009 can run in parallel.
- Foundational tests T015-T017 can run in parallel after skeletons exist.
- US1 tests T019-T025 can run in parallel before US1 implementation.
- US2 tests T043-T048 can run in parallel before US2 implementation.
- US3 tests T057-T061 can run in parallel before US3 implementation.
- Documentation tasks T069-T070 can run in parallel with final validation.

---

## Parallel Examples

### User Story 1

```text
Task: "T021 [P] [US1] Add unit tests for parquet task loading and required field validation in tests/unit/test_swebench_dataset.py"
Task: "T022 [P] [US1] Add unit tests for Docker command wrapper success, failure, and timeout mapping in tests/unit/test_docker_cli.py"
Task: "T024 [P] [US1] Add unit tests for container-backed read/write/search tools in tests/unit/test_container_tools.py"
```

### User Story 2

```text
Task: "T043 [P] [US2] Add CLI contract tests for coding-agent sandbox register in tests/contract/test_cli_sandbox_contract.py"
Task: "T045 [P] [US2] Add unit tests for registry save/load/update behavior in tests/unit/test_sandbox_registry.py"
Task: "T048 [P] [US2] Add integration test that reusable sandbox resets between two task runs in tests/integration/test_sandbox_reuse.py"
```

### User Story 3

```text
Task: "T057 [P] [US3] Add unit tests for parsing FAIL_TO_PASS and PASS_TO_PASS metadata in tests/unit/test_swebench_validation.py"
Task: "T060 [P] [US3] Add contract test for --include-pass-to-pass CLI behavior in tests/contract/test_cli_swebench_run_contract.py"
Task: "T061 [P] [US3] Add integration test for rejecting container test commands outside the allowed set in tests/integration/test_swebench_validation_integration.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 setup.
2. Complete Phase 2 foundational executor and model changes.
3. Complete Phase 3 for one sandboxed task run with fake Docker validation.
4. Stop and validate `coding-agent swebench run` independently.

### Incremental Delivery

1. Deliver US1 to prove one sandboxed task can run and produce artifacts.
2. Add US2 to make sandbox registration and reuse practical.
3. Add US3 to enforce SWE-Bench validation metadata behavior.
4. Finish with cross-cutting docs, suite validation, and responsibility audit.

### Compatibility Strategy

Existing `coding-agent run` for prepared local workspaces must remain usable
throughout. Any executor or model changes should include regression coverage
before sandbox-specific behavior is added.

---

## Notes

- [P] tasks are parallelizable because they touch distinct files or can be done before dependent implementation.
- Story labels map directly to user stories in `spec.md`.
- Docker-dependent tests should use fake Docker command runners unless explicitly marked as manual quickstart validation.
- Keep Docker subprocess details out of `agent.py`; use sandbox modules and the `ToolExecutor` protocol.
- Commit after each phase or logical group when using Spec Kit git hooks.
