# Tasks: Agent Runtime Environment Refactor

**Input**: Design documents from `specs/003-agent-runtime-refactor/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli-contract.md`, `quickstart.md`

**Tests**: Required. The feature specification defines independent test criteria for each user story, and the project constitution requires test integrity rather than fixture-only behavior. Write the listed tests first, verify they fail for the intended reason, then implement.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently after the foundational work is complete.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on incomplete tasks in the same phase.
- **[Story]**: User story label for story phases only.
- Every task includes at least one exact file path.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the refactor workspace, source references, and test scaffolding without changing runtime behavior.

- [ ] T001 Read the source-backed implementation references and record exact source sections to consult in `specs/003-agent-runtime-refactor/research.md`
- [ ] T002 [P] Create the new runtime contract test file skeleton in `tests/contract/test_cli_swebench_runtime_contract.py`
- [ ] T003 [P] Create the official-style runtime integration test file skeleton in `tests/integration/test_swebench_official_runtime.py`
- [ ] T004 [P] Create the adapted TestSpec unit test file skeleton in `tests/unit/test_swebench_testspec.py`
- [ ] T005 [P] Create the source-backed repo metadata unit test file skeleton in `tests/unit/test_swebench_repo_specs.py`
- [ ] T006 [P] Create the script builder unit test file skeleton in `tests/unit/test_swebench_script_builders.py`
- [ ] T007 [P] Create the image graph unit test file skeleton in `tests/unit/test_swebench_images.py`
- [ ] T008 [P] Create the grading unit test file skeleton in `tests/unit/test_swebench_grading.py`
- [ ] T009 [P] Add official-runtime fake Docker helpers in `tests/unit/fakes/test_swebench_runtime_fakes.py`
- [ ] T010 [P] Add shared SWE-Bench parquet fixture builders in `tests/helpers/swebench_fixtures.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add shared domain models, metadata boundaries, and common helpers required by all user stories.

**CRITICAL**: No user story implementation can begin until this phase is complete.

- [ ] T011 Add source-backed runtime dataclasses for benchmark task records, adapted specs, runtime lineage, prepared environments, validation sets, eval reports, and compatibility paths in `src/coding_agent/models.py`
- [ ] T012 Extend SWE-Bench dataset normalization with repo version, environment setup commit, eval script, test patch, and explicit metadata errors in `src/coding_agent/swebench/dataset.py`
- [ ] T013 [P] Create source-backed repo/version metadata lookup boundaries and review-status types in `src/coding_agent/swebench/repo_specs.py`
- [ ] T014 [P] Create adapted TestSpec construction interfaces without production metadata values in `src/coding_agent/swebench/testspec.py`
- [ ] T015 [P] Create source-derived setup/eval script builder interfaces in `src/coding_agent/swebench/script_builders.py`
- [ ] T016 [P] Create image graph planning interfaces for base, env, and instance layers in `src/coding_agent/swebench/images.py`
- [ ] T017 [P] Create official-style grading parser interfaces in `src/coding_agent/swebench/grading.py`
- [ ] T018 Update SWE-Bench package exports for new modules in `src/coding_agent/swebench/__init__.py`
- [ ] T019 Add explicit runtime path and compatibility markers to sandbox metadata serialization in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T020 Add an implementation compliance checklist for source-backed mappings and no test gaming in `specs/003-agent-runtime-refactor/quickstart.md`

**Checkpoint**: Foundational types and module boundaries exist; story work can proceed in priority order or in parallel if staffed.

---

## Phase 3: User Story 1 - Prepare Official-Style Runtime Environments (Priority: P1) MVP

**Goal**: A developer can prepare an official-style task runtime, see missing image failures before agent execution, and reuse compatible runtime layers while still creating a task-specific starting point.

**Independent Test**: Select one supported task and verify that runtime preparation records task identity, repository identity, base revision, image lineage, build/reuse status, and readiness before any model backend is initialized.

### Tests for User Story 1

- [ ] T021 [P] [US1] Add contract tests for `coding-agent swebench prepare` argument parsing, no `--registry` requirement, and `--build-missing` handling in `tests/contract/test_cli_swebench_runtime_contract.py`
- [ ] T022 [P] [US1] Add contract tests for `coding-agent swebench prepare` active index options, readiness output, and missing image failures in `tests/contract/test_cli_swebench_runtime_contract.py`
- [ ] T023 [P] [US1] Add dataset normalization tests for supported repo, unsupported repo, and missing source-backed metadata in `tests/unit/test_swebench_dataset.py`
- [ ] T024 [P] [US1] Add source-backed repo metadata tests that reject fixture-only mappings and require source references in `tests/unit/test_swebench_repo_specs.py`
- [ ] T025 [P] [US1] Add adapted TestSpec tests for deterministic repo path, env name, validation metadata, and image keys in `tests/unit/test_swebench_testspec.py`
- [ ] T026 [P] [US1] Add script builder tests for repo setup, environment setup, eval script derivation, and missing metadata errors in `tests/unit/test_swebench_script_builders.py`
- [ ] T027 [P] [US1] Add image graph tests for base -> env -> instance ordering, reuse detection, and no-build failure in `tests/unit/test_swebench_images.py`
- [ ] T028 [P] [US1] Add fake-Docker integration tests for prepare readiness metadata and active environment indexing in `tests/integration/test_swebench_official_runtime.py`

### Implementation for User Story 1

- [ ] T029 [US1] Implement source-backed local SWE-Bench Lite repo/version metadata from `specs/003-agent-runtime-refactor/runtime-image-audit.md` with source references and review status in `src/coding_agent/swebench/repo_specs.py`
- [ ] T030 [US1] Implement `BenchmarkTaskRecord` normalization from parquet rows, including repo version and validation fields, in `src/coding_agent/swebench/dataset.py`
- [ ] T031 [US1] Implement adapted TestSpec creation from `BenchmarkTaskRecord` plus `RepoVersionSpec` in `src/coding_agent/swebench/testspec.py`
- [ ] T032 [US1] Implement repo setup, environment setup, instance setup, and eval script builders from adapted TestSpec in `src/coding_agent/swebench/script_builders.py`
- [ ] T033 [US1] Implement deterministic base, env, and instance image key derivation matching `specs/003-agent-runtime-refactor/runtime-image-audit.md` in `src/coding_agent/swebench/images.py`
- [ ] T034 [US1] Implement Docker image existence checks and missing-image planning in `src/coding_agent/swebench/images.py`
- [ ] T035 [US1] Implement opt-in image builds in base -> env -> instance order with built/reused image recording in `src/coding_agent/swebench/images.py`
- [ ] T036 [US1] Add Docker CLI build, inspect, create, copy, and exec helpers needed by official-style image preparation in `src/coding_agent/sandbox/docker_cli.py`
- [ ] T037 [US1] Update task environment creation to use the official-style instance image and source-backed repo path in `src/coding_agent/sandbox/manager.py`
- [ ] T038 [US1] Implement `prepare` orchestration that resolves task specs, checks/builds images, creates an active prepared environment, and writes `sandbox.json` in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T039 [US1] Implement active prepared environment indexing, readiness checks, and replace-existing behavior for `prepare` in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T040 [US1] Wire the `swebench prepare` CLI command with exit-code mapping in `src/coding_agent/cli.py`
- [ ] T041 [US1] Run the US1 red/green checks from `specs/003-agent-runtime-refactor/quickstart.md` and update any command drift in `specs/003-agent-runtime-refactor/quickstart.md`

**Checkpoint**: User Story 1 is independently usable as the MVP.

---

## Phase 4: User Story 2 - Run Agent Work Through the Prepared Environment (Priority: P2)

**Goal**: A developer can run a selected task from a prepared environment while preserving budgets, model flow, repository tool confinement, and the artifact contract.

**Independent Test**: Prepare one task and run it with the mock backend, then confirm repository tools operate only in the selected environment and `trajectory.jsonl`, `trajectory.json`, `summary.json`, `final.patch`, `prediction.jsonl`, and `sandbox.json` are produced.

### Tests for User Story 2

- [ ] T042 [P] [US2] Update `swebench run` contract tests to remove the `--registry` requirement and assert official-style runtime dispatch in `tests/contract/test_cli_swebench_run_contract.py`
- [ ] T043 [P] [US2] Add `swebench run` contract tests for active index lookup, cleanup flag, absence of `--build-missing`, and no image build behavior in `tests/contract/test_cli_swebench_runtime_contract.py`
- [ ] T044 [P] [US2] Add integration tests for run artifact creation from a prepared environment with the mock backend and fake Docker in `tests/integration/test_swebench_official_runtime.py`
- [ ] T045 [P] [US2] Add integration tests for prepare then run using the active environment index in `tests/integration/test_swebench_official_runtime.py`
- [ ] T046 [P] [US2] Add runtime failure diagnostic tests that preserve partial artifacts after agent start in `tests/integration/test_errored_run_diagnostics.py`
- [ ] T047 [P] [US2] Add container tool confinement tests for official-style prepared environments in `tests/unit/test_container_tools.py`

### Implementation for User Story 2

- [ ] T048 [US2] Refactor `run_swebench_task` orchestration to require an active prepared environment and remove default legacy registry dependency in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T049 [US2] Implement `run_prepared` orchestration with active environment metadata validation in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T050 [US2] Update active prepared environment index load/save metadata for repo version, runtime lineage, and sandbox JSON paths in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T051 [US2] Inject `ContainerToolExecutor` using the prepared environment repo path and official validation set in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T052 [US2] Preserve post-start failure artifacts including `summary.json`, `trajectory.jsonl`, `trajectory.json`, `prediction.jsonl`, `final.patch`, and `sandbox.json` in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T053 [US2] Export final container diff and prediction JSONL from the official-style prepared environment in `src/coding_agent/swebench/prediction.py`
- [ ] T054 [US2] Add runtime lineage, validation source, selected validation mode, and artifact locations to run summaries in `src/coding_agent/trajectory/summary.py`
- [ ] T055 [US2] Wire the `swebench run` CLI command to official-style prepared-environment orchestration and exit-code mapping in `src/coding_agent/cli.py`
- [ ] T056 [US2] Run the US2 prepare-then-run checks from `specs/003-agent-runtime-refactor/quickstart.md`

**Checkpoint**: User Stories 1 and 2 both work independently with the mock backend and fake Docker tests.

---

## Phase 5: User Story 3 - Validate With Source-Backed Benchmark Semantics (Priority: P3)

**Goal**: In-run validation commands come from source-backed task metadata, final review executes the adapted TestSpec `eval_script`, regression checks are opt-in, disallowed commands are rejected, and validation-only changes are excluded from final patches.

**Independent Test**: Select a task with fix-verification metadata, run validation, verify accepted in-run commands are derived from that task, final review executes the adapted TestSpec `eval_script`, opt-in regression checks are reported separately, disallowed validation requests are recorded, and validation-only test files do not appear in `final.patch`.

### Tests for User Story 3

- [ ] T057 [P] [US3] Add validation set tests for default `FAIL_TO_PASS`, opt-in `PASS_TO_PASS`, and source-backed command provenance in `tests/unit/test_swebench_validation.py`
- [ ] T058 [P] [US3] Add official-style `eval_script` output grading tests for fixed checks, regression checks, missing output, and unparsable output in `tests/unit/test_swebench_grading.py`
- [ ] T059 [P] [US3] Add disallowed validation command rejection tests for the container test tool in `tests/unit/test_tool_run_tests.py`
- [ ] T060 [P] [US3] Add final patch exclusion tests for validation-only task files and patches in `tests/unit/test_patch.py`
- [ ] T061 [P] [US3] Add integration tests for validation patch apply/reset behavior in `tests/integration/test_swebench_validation_integration.py`

### Implementation for User Story 3

- [ ] T062 [US3] Replace registered-template default validation with adapted TestSpec validation while keeping explicit compatibility fallback isolated in `src/coding_agent/swebench/validation.py`
- [ ] T063 [US3] Implement validation command allow-list construction and disallowed command recording in `src/coding_agent/swebench/validation.py`
- [ ] T064 [US3] Implement official-style adapted TestSpec `eval_script` output parsing into `EvalReport` in `src/coding_agent/swebench/grading.py`
- [ ] T065 [US3] Integrate final `eval_script` execution and grading into run summaries and sandbox metadata in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T066 [US3] Ensure test patches are applied only for validation and reset or excluded before final diff export in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T067 [US3] Update container-backed `run_tests` enforcement to reject commands outside the selected validation set in `src/coding_agent/tools/run_tests.py`
- [ ] T068 [US3] Run the US3 validation checks from `specs/003-agent-runtime-refactor/quickstart.md`

**Checkpoint**: User Stories 1, 2, and 3 provide an official-style single-task benchmark runtime path with source-backed validation.

---

## Phase 6: User Story 4 - Migrate Without Breaking Existing Workflows (Priority: P4)

**Goal**: New benchmark runs use the official-style path by default, while existing prepared-workspace and explicit legacy sandbox flows remain usable and visibly marked as compatibility behavior.

**Independent Test**: Run existing prepared-workspace flow and legacy sandbox registration/list flow after the refactor, then verify new benchmark commands do not use the legacy registry unless an explicit compatibility command is selected.

### Tests for User Story 4

- [ ] T069 [P] [US4] Add prepared-workspace compatibility regression tests in `tests/integration/test_prepared_workspace_compatibility.py`
- [ ] T070 [P] [US4] Add legacy sandbox register/list compatibility tests with compatibility markers in `tests/contract/test_cli_sandbox_contract.py`
- [ ] T071 [P] [US4] Add tests proving new benchmark prepare/run commands do not read `SandboxRegistry` by default in `tests/contract/test_cli_swebench_runtime_contract.py`
- [ ] T072 [P] [US4] Add out-of-scope batch benchmark orchestration tests for the new runtime path in `tests/contract/test_cli_swebench_runtime_contract.py`

### Implementation for User Story 4

- [ ] T073 [US4] Preserve existing prepared-workspace `coding-agent run` behavior without benchmark runtime configuration in `src/coding_agent/cli.py`
- [ ] T074 [US4] Preserve `coding-agent sandbox register` and `coding-agent sandbox list` as explicit compatibility commands in `src/coding_agent/cli.py`
- [ ] T075 [US4] Label legacy registry usage as compatibility behavior in sandbox metadata and help text in `src/coding_agent/sandbox/registry.py`
- [ ] T076 [US4] Prevent new benchmark runtime paths from silently falling back to `SandboxRegistry` in `src/coding_agent/swebench/sandbox_run.py`
- [ ] T077 [US4] Keep current batch commands isolated from the new official-style runtime path or return an explicit out-of-scope error for new runtime batch requests in `src/coding_agent/cli.py`
- [ ] T078 [US4] Run the US4 migration checks from `specs/003-agent-runtime-refactor/quickstart.md`

**Checkpoint**: Migration behavior is observable, reversible through explicit compatibility commands, and default benchmark runs avoid the legacy registry path.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate the whole refactor, tighten documentation, and check for constitution compliance.

- [ ] T079 [P] Update developer-facing runtime notes and command examples in `README.md`
- [ ] T080 [P] Update source-backed metadata documentation and review status notes in `specs/003-agent-runtime-refactor/research.md`
- [ ] T081 Run focused unit tests listed in `specs/003-agent-runtime-refactor/quickstart.md`
- [ ] T082 Run focused contract tests listed in `specs/003-agent-runtime-refactor/quickstart.md`
- [ ] T083 Run focused integration tests listed in `specs/003-agent-runtime-refactor/quickstart.md`
- [ ] T084 Run full verification command `python -m pytest -q` and record the result in `specs/003-agent-runtime-refactor/quickstart.md`
- [ ] T085 Review `src/coding_agent/swebench/repo_specs.py` for undocumented static mappings, fixture-only branches, and expected-output shortcuts
- [ ] T086 Review `src/coding_agent/swebench/testspec.py` for undocumented static mappings, fixture-only branches, and expected-output shortcuts
- [ ] T087 Review `src/coding_agent/swebench/script_builders.py` for undocumented static mappings, fixture-only branches, and expected-output shortcuts
- [ ] T088 Review `src/coding_agent/swebench/images.py` for undocumented static mappings, fixture-only branches, and expected-output shortcuts
- [ ] T089 Review `src/coding_agent/swebench/validation.py` for undocumented static mappings, fixture-only branches, and expected-output shortcuts
- [ ] T090 Review `src/coding_agent/swebench/sandbox_run.py` for broad coupling and split helper functions if responsibilities exceed the plan boundaries
- [ ] T091 Run `git diff --check -- specs/003-agent-runtime-refactor src tests README.md` and fix whitespace issues in changed files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup completion and blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; MVP scope.
- **User Story 2 (Phase 4)**: Depends on Foundational and integrates most naturally after US1 prepared environments exist.
- **User Story 3 (Phase 5)**: Depends on Foundational; can start after TestSpec and validation interfaces exist, but final integration depends on US2 run orchestration.
- **User Story 4 (Phase 6)**: Depends on Foundational; can run in parallel with US2/US3 if compatibility tests are kept isolated.
- **Polish (Phase 7)**: Depends on all desired user stories.

### User Story Dependencies

- **US1 (P1)**: No dependency on other stories after Foundational.
- **US2 (P2)**: Uses prepared environment and image lineage from US1.
- **US3 (P3)**: Uses adapted TestSpec from US1 and run artifact integration from US2.
- **US4 (P4)**: Uses CLI/runtime boundaries from US1 and US2, but compatibility tests can be written early.

### Within Each User Story

- Write tests first and verify they fail for the expected reason.
- Implement domain models and services before CLI dispatch.
- Implement CLI dispatch before integration quickstart checks.
- Complete each story checkpoint before relying on it in a later story.

### Parallel Opportunities

- T002-T010 can run in parallel after T001.
- T013-T017 can run in parallel after T011-T012 are understood.
- US1 test tasks T021-T028 can run in parallel.
- US2 test tasks T042-T047 can run in parallel.
- US3 test tasks T057-T061 can run in parallel.
- US4 test tasks T069-T072 can run in parallel.
- Documentation tasks T079-T080 can run in parallel with final review tasks T085-T089 after implementation stabilizes.

---

## Parallel Example: User Story 1

```text
Task: "T021 [P] [US1] Add contract tests for coding-agent swebench prepare argument parsing, no --registry requirement, and --build-missing handling in tests/contract/test_cli_swebench_runtime_contract.py"
Task: "T024 [P] [US1] Add source-backed repo metadata tests that reject fixture-only mappings and require source references in tests/unit/test_swebench_repo_specs.py"
Task: "T027 [P] [US1] Add image graph tests for base -> env -> instance ordering, reuse detection, and no-build failure in tests/unit/test_swebench_images.py"
```

## Parallel Example: User Story 2

```text
Task: "T042 [P] [US2] Update swebench run contract tests to remove the --registry requirement and assert official-style runtime dispatch in tests/contract/test_cli_swebench_run_contract.py"
Task: "T044 [P] [US2] Add integration tests for run artifact creation from a prepared environment with the mock backend and fake Docker in tests/integration/test_swebench_official_runtime.py"
Task: "T047 [P] [US2] Add container tool confinement tests for official-style prepared environments in tests/unit/test_container_tools.py"
```

## Parallel Example: User Story 3

```text
Task: "T057 [P] [US3] Add validation set tests for default FAIL_TO_PASS, opt-in PASS_TO_PASS, and source-backed command provenance in tests/unit/test_swebench_validation.py"
Task: "T058 [P] [US3] Add official-style eval_script output grading tests for fixed checks, regression checks, missing output, and unparsable output in tests/unit/test_swebench_grading.py"
Task: "T060 [P] [US3] Add final patch exclusion tests for validation-only task files and patches in tests/unit/test_patch.py"
```

## Parallel Example: User Story 4

```text
Task: "T069 [P] [US4] Add prepared-workspace compatibility regression tests in tests/integration/test_prepared_workspace_compatibility.py"
Task: "T070 [P] [US4] Add legacy sandbox register/list compatibility tests with compatibility markers in tests/contract/test_cli_sandbox_contract.py"
Task: "T071 [P] [US4] Add tests proving new benchmark prepare/run commands do not read SandboxRegistry by default in tests/contract/test_cli_swebench_runtime_contract.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 setup tasks.
2. Complete Phase 2 foundational runtime contracts and module boundaries.
3. Complete Phase 3 User Story 1 tests and implementation.
4. Stop and validate prepare behavior independently.

### Incremental Delivery

1. Deliver US1 so official-style runtime preparation is available and auditable.
2. Deliver US2 so run from a prepared environment preserves current artifacts.
3. Deliver US3 so validation semantics are source-backed and final patches stay clean.
4. Deliver US4 so migration compatibility remains explicit and observable.
5. Run final quickstart and full pytest verification.

### Parallel Team Strategy

1. Complete setup and foundational tasks together.
2. Assign US1 implementation to the runtime preparation owner.
3. Assign US2 implementation to the agent orchestration and artifact owner.
4. Assign US3 implementation to the validation and grading owner.
5. Assign US4 implementation to the CLI compatibility owner.

---

## Independent Test Criteria Summary

- **US1**: Preparing a supported task records task identity, repo identity, base revision, image lineage, build/reuse status, and readiness before model execution.
- **US2**: Run operates only in the selected prepared environment and produces the standard artifact set plus runtime metadata.
- **US3**: In-run validation uses selected task metadata, final review executes the adapted TestSpec `eval_script`, regression checks are opt-in, disallowed commands are rejected, and validation-only changes are absent from `final.patch`.
- **US4**: Existing prepared-workspace and explicit legacy sandbox flows still work, while new benchmark runs use official-style runtime by default.

## Notes

- Do not implement behavior by branching on current test names, fixture instance IDs, expected outputs, or sample-only values.
- Any static mapping in `src/coding_agent/swebench/repo_specs.py` must be domain metadata with source references and review status.
- Do not import the local `SWE-bench/` checkout at runtime; it is a reference source only.
- Keep batch benchmark orchestration out of scope for the new runtime path.
- Commit after each task or coherent task group if using the optional git hook workflow.
