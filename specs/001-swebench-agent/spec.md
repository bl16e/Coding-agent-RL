# Feature Specification: SWE-Bench Lite Coding Agent

**Feature Branch**: `001-swebench-agent`

**Created**: 2026-06-04

**Status**: Draft

**Input**: User description: "I want to implement a coding agent that can run SWE-Bench Lite, includes read_file, write_file, search_code, run_tests tools, and records the complete Trajectory."

## Clarifications

### Session 2026-06-04

- Q: Trajectory 的交付形态应该是什么？ → A: JSONL step log + final patch + summary 文件
- Q: run_tests 应该允许执行哪些测试？ → A: 任务/运行配置中预先声明的允许测试命令
- Q: Trajectory 中 agent 的“决策过程”应记录到什么粒度？ → A: 每步记录简短 reasoning summary、下一步意图和工具选择原因
- Q: write_file 的修改语义应该是什么？ → A: 接受完整文件内容写入，系统负责生成最终 patch
- Q: agent run 的停止条件和预算应该如何定义？ → A: 每个 Agent Run 配置声明最大步数、总耗时和单次测试超时

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a Benchmark Task (Priority: P1)

A developer selects a SWE-Bench Lite task and starts an agent run so the agent can inspect the repository, make changes, run tests, and produce a final result for that task.

**Why this priority**: This is the core user value. Without an end-to-end task run, the tool set and trajectory records cannot be validated.

**Independent Test**: Can be tested by running the agent on one known SWE-Bench Lite task and verifying that it attempts the task using only the supported tools and produces a final status.

**Acceptance Scenarios**:

1. **Given** a valid SWE-Bench Lite task with repository context, **When** the developer starts a run, **Then** the agent reads relevant files, searches code, writes a patch when needed, runs tests, and reports the final outcome.
2. **Given** a task that cannot be solved within the configured run limits, **When** the run ends, **Then** the agent reports an incomplete or failed outcome with the reason captured in the trajectory.
3. **Given** an Agent Run with configured limits, **When** the agent reaches maximum steps, total runtime, or single-test timeout, **Then** the run stops or the test attempt ends with the budget reason recorded.

---

### User Story 2 - Use the Required Tool Set (Priority: P2)

A developer needs the agent to interact with code through a constrained tool interface containing read_file, write_file, search_code, and run_tests.

**Why this priority**: SWE-Bench Lite evaluation must be reproducible and auditable. A constrained tool set makes behavior easier to inspect.

**Independent Test**: Can be tested by running a controlled task and verifying that every repository interaction is represented by one of the four supported tool types.

**Acceptance Scenarios**:

1. **Given** a running agent, **When** it needs file contents, **Then** it uses read_file and records the requested path and result.
2. **Given** a running agent, **When** it needs to modify code, **Then** it uses write_file with complete file content and records the target path and write result.
3. **Given** a running agent, **When** it needs to locate relevant code, **Then** it uses search_code and records the query and matches.
4. **Given** a running agent, **When** it needs validation feedback, **Then** it uses run_tests and records the command summary and result.
5. **Given** a running agent, **When** it requests test execution, **Then** run_tests only executes a test command that was pre-declared for the task or run configuration.

---

### User Story 3 - Review Complete Trajectory (Priority: P3)

A developer reviews the complete Trajectory after a run to understand what the agent observed, decided, changed, tested, and concluded.

**Why this priority**: Trajectory records are required for debugging, benchmark analysis, and reproducibility.

**Independent Test**: Can be tested by completing a run and verifying that the saved Trajectory contains every agent step in order, including tool calls, tool results, reasoning summaries, file changes, test outcomes, and final status.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the developer opens the Trajectory, **Then** every step is shown in chronological order with enough detail to replay the agent's work at the level of tool inputs and outputs.
2. **Given** a run that ends with an error, **When** the developer opens the Trajectory, **Then** the error point, prior tool activity, and final failure status are captured.
3. **Given** a completed run, **When** the developer reviews an agent decision step in the Trajectory, **Then** the step includes a brief reasoning summary, next-step intent, and reason for any tool choice.

### Edge Cases

- The selected SWE-Bench Lite task is missing required repository context or metadata.
- A requested file path is not found or is outside the allowed task workspace.
- A search returns no matches or too many matches to review efficiently.
- A write_file operation would overwrite changes from a previous tool step in the same run.
- Tests fail, time out, or cannot be executed in the task environment.
- The agent reaches a run limit before producing a patch or final answer.
- Trajectory persistence fails while the run is in progress.
- The agent requests a test command that is not pre-declared for the task or run configuration.
- The Agent Run configuration omits maximum steps, total runtime, or single-test timeout.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow a developer to start an agent run for a selected SWE-Bench Lite task.
- **FR-002**: The system MUST provide exactly these repository interaction tools for the agent: read_file, write_file, search_code, and run_tests.
- **FR-003**: The system MUST record every agent step in a JSONL Trajectory step log, including step order, action type, tool input, tool output summary, outcome, and timestamp or ordering marker; agent decision steps MUST also include brief reasoning summary, next-step intent, and tool selection reason when a tool is chosen.
- **FR-004**: The system MUST record the final run outcome as solved, failed, incomplete, or errored.
- **FR-005**: The system MUST prevent repository access that is outside the selected task workspace.
- **FR-006**: The system MUST record each file modification made by write_file, including the target path and whether the complete-file write succeeded.
- **FR-007**: The system MUST record each test attempt made by run_tests, including whether tests passed, failed, timed out, or could not run.
- **FR-008**: The system MUST surface enough failure detail for invalid tasks, invalid paths, failed writes, and failed test execution to diagnose the run from the Trajectory alone.
- **FR-009**: The system MUST preserve Trajectory data when a run ends normally, fails, or errors after at least one agent step has started.
- **FR-010**: The system MUST expose the completed Trajectory to the developer after the run finishes as a JSONL step log, a final patch file, and a summary file.
- **FR-011**: The system MUST restrict run_tests to test commands pre-declared by the Benchmark Task or Agent Run configuration.
- **FR-012**: The system MUST reject and record any run_tests request for a non-declared test command.
- **FR-013**: The system MUST define write_file as a complete-file content write operation.
- **FR-014**: The system MUST generate the final patch from the before-and-after file states created during the Agent Run.
- **FR-015**: The system MUST require each Agent Run configuration to declare maximum steps, total runtime, and single-test timeout limits.
- **FR-016**: The system MUST stop the Agent Run or current test attempt when a declared budget limit is reached and record the budget reason in the Trajectory.

### Key Entities *(include if feature involves data)*

- **Benchmark Task**: A SWE-Bench Lite problem instance selected for an agent run, including task identity, repository context, problem statement, and expected validation context.
- **Agent Run**: One attempt to solve a selected Benchmark Task, including start state, current status, configured limits, final outcome, and associated Trajectory.
- **Tool Call**: A single use of read_file, write_file, search_code, or run_tests, including input, output summary, success or failure status, and ordering within the run.
- **Trajectory**: The ordered JSONL step log of an Agent Run, including agent step summaries, decision-step reasoning summaries, next-step intents, tool selection reasons, Tool Calls, file modifications, test attempts, errors, and final outcome.
- **Final Patch**: The aggregate code change produced by an Agent Run, stored separately from the step log for evaluation and review.
- **Run Summary**: A concise file describing the Agent Run identity, final outcome, key files changed, test outcome summary, and error state if present.
- **File Modification**: A complete-file write made during an Agent Run, including target path, previous relationship to the run, new content result, and write status.
- **Test Result**: The validation outcome from a run_tests Tool Call, including pass, fail, timeout, or execution error status.
- **Allowed Test Command**: A test command declared by the Benchmark Task or Agent Run configuration that run_tests may execute.
- **Run Budget**: The maximum steps, total runtime, and single-test timeout declared for one Agent Run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can run one selected SWE-Bench Lite task end to end and receive a final outcome in 100% of completed evaluation attempts.
- **SC-002**: For every completed run, 100% of tool calls are represented in the Trajectory in chronological order.
- **SC-003**: For every run with file modifications, 100% of modified file paths and write outcomes are visible in the Trajectory.
- **SC-004**: For every run with test execution, 100% of test attempts have a recorded pass, fail, timeout, or execution error outcome.
- **SC-005**: A reviewer can identify the final outcome, last successful tool call, and any error point from the Trajectory in under 2 minutes.
- **SC-006**: Every finished run produces all three review artifacts: JSONL step log, final patch, and summary file.
- **SC-007**: For every completed run, 100% of agent decision steps in the Trajectory include a brief reasoning summary and next-step intent.
- **SC-008**: 100% of runs stopped by a budget limit record which limit was reached in the Trajectory and summary file.

## Clarifications & Explicit Defaults

- This specification covers one selected SWE-Bench Lite task per agent run; batch orchestration can be specified separately.
- The required repository interaction tool set is limited to read_file, write_file, search_code, and run_tests.
- The complete Trajectory must be durable enough to inspect after the run finishes or errors and is delivered as a JSONL step log, final patch, and summary file.
- run_tests executes only test commands pre-declared by the Benchmark Task or Agent Run configuration.
- Trajectory records include concise decision summaries, not a requirement to persist full raw model output.
- write_file accepts complete file content rather than patch fragments; final patches are generated by comparing before-and-after file states.
- Each Agent Run declares maximum steps, total runtime, and single-test timeout before it starts.
- OpenAI-compatible model runs use root `.env` or process environment values for `PROVIDER`, `MODEL`, `API_KEY`, and `BASE_URL`.
- The specification describes user-visible behavior and benchmark workflow requirements; implementation technology choices are deferred to planning.
