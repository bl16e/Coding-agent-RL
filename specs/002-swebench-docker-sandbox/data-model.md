# Data Model: SWE-Bench Docker Sandbox

## SwebenchTaskRecord

- `instance_id`: unique SWE-Bench Lite task identifier.
- `repo`: repository identifier such as `owner/name`.
- `base_commit`: commit used as the starting code state.
- `problem_statement`: issue text presented to the agent.
- `FAIL_TO_PASS`: list of test identifiers expected to pass after a correct fix.
- `PASS_TO_PASS`: optional list of regression test identifiers.
- `version`: optional dataset version/environment hint.
- `environment_setup_commit`: optional commit used by official setup metadata.

Validation:
- `instance_id`, `repo`, `base_commit`, `problem_statement`, and
  `FAIL_TO_PASS` are required for default sandboxed runs.
- `PASS_TO_PASS` may be empty and is used only when regression validation is
  explicitly enabled.

## BaseSandbox

- `repo`: repository identifier the sandbox supports.
- `image`: configured Docker image name or tag.
- `repo_path`: absolute path inside the container where the repository lives.
- `official_compatible`: boolean marker that the image targets official
  SWE-Bench-compatible behavior.
- `created_at` or `registered_at`: timestamp for registry inspection.

Validation:
- Each repository may have one active base sandbox registration.
- The image must exist before a task run starts.
- Missing base sandbox registration is a pre-run configuration error.

## SandboxRegistry

- `path`: registry file path.
- `sandboxes`: mapping from repository id to BaseSandbox.

Validation:
- Registry JSON must be readable before sandboxed runs.
- Duplicate repo entries resolve to the last explicitly registered entry only
  when registration is requested by the developer.

## ValidationTestSet

- `fail_to_pass`: tests derived from task `FAIL_TO_PASS`.
- `pass_to_pass`: tests derived from task `PASS_TO_PASS` when enabled.
- `allowed_commands`: exact commands the agent may request through `run_tests`.
- `include_pass_to_pass`: boolean option.

Validation:
- Default validation includes only `FAIL_TO_PASS`.
- Every accepted `run_tests` command must be present in `allowed_commands`.

## TaskSandbox

- `container_name`: deterministic container name for the selected run.
- `base_sandbox`: BaseSandbox used to create or reuse the task environment.
- `instance_id`: task identity.
- `repo`: repository identity.
- `base_commit`: commit to reset before agent actions begin.
- `repo_path`: repository path inside the container.
- `status`: `pending`, `ready`, `running`, `stopped`, or `error`.

State transitions:
- `pending -> ready` after image lookup and workspace reset succeed.
- `ready -> running` when the agent starts tool execution.
- `running -> stopped | error` when the run ends or the container fails.

Validation:
- A new task must reset to `base_commit` before the first model action.
- Prior run artifacts are stored outside the task workspace and survive reset.

## SandboxedAgentRun

- `run_id`: unique run identifier.
- `task_record`: SwebenchTaskRecord.
- `task_sandbox`: TaskSandbox.
- `validation_test_set`: ValidationTestSet.
- `budget`: existing RunBudget.
- `model_name`: model used for the run.
- `status`: existing terminal status values.
- `artifacts`: trajectory, final patch, summary, prediction, and sandbox
  metadata paths.

Validation:
- Existing AgentRun state transitions still apply.
- The summary must include sandbox image, repo path, base commit, and validation
  mode for inspection.

## ContainerToolResult

Uses the existing ToolExecutionResult shape with container-specific execution
details in bounded output metadata.

Validation:
- `read_file`, `write_file`, and `search_code` paths resolve under
  `repo_path` inside the selected container.
- `run_tests` executes inside the selected container and records stdout/stderr
  summaries using the existing TestResult rules.
