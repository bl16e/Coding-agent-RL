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

## BaseImage

- `repo`: repository identifier the image supports.
- `image`: configured Docker image name or tag.
- `repo_path`: absolute path inside the container where the repository lives.
- `official_compatible`: boolean marker that the image targets official
  SWE-Bench-compatible behavior.
- `compatibility_source`: optional human-readable note or source explaining how
  the official-compatible marker was established.
- `validation_command_template`: optional explicit fallback command template
  used only when official SWE-Bench TestSpec/eval script data is unavailable.
- `created_at` or `registered_at`: timestamp for registry inspection.

Validation:
- Each repository may have one active base image registration.
- The image must exist before a task run starts.
- Sandboxed SWE-Bench runs require `official_compatible` to be true.
- If official TestSpec/eval script data is unavailable, the registration must
  provide `validation_command_template` before model execution can begin.
- Missing base image registration is a pre-run configuration error.

## SandboxRegistry

- `path`: registry file path.
- `sandboxes`: mapping from repository id to BaseImage.

Validation:
- Registry JSON must be readable before sandboxed runs.
- Duplicate repo entries resolve to the last explicitly registered entry only
  when registration is requested by the developer.

## ValidationTestSet

- `fail_to_pass`: tests derived from task `FAIL_TO_PASS`.
- `pass_to_pass`: tests derived from task `PASS_TO_PASS` when enabled.
- `command_source`: `official_testspec` or `registered_template`.
- `eval_script`: official SWE-Bench eval script content or reference when available.
- `allowed_commands`: exact commands the agent may request through `run_tests`.
- `include_pass_to_pass`: boolean option.

Validation:
- Default validation includes only `FAIL_TO_PASS`.
- Official SWE-Bench TestSpec/eval script behavior is preferred for converting
  identifiers into allowed commands.
- Registered fallback templates may be used only when official TestSpec/eval
  script data is unavailable.
- Missing official data and missing fallback template is a pre-run configuration
  error.
- Every accepted `run_tests` command must be present in `allowed_commands`.

## TaskSandbox

- `container_name`: deterministic container name for the selected run.
- `base_image`: BaseImage used to create the task container.
- `instance_id`: task identity.
- `repo`: repository identity.
- `base_commit`: commit to reset before agent actions begin.
- `repo_path`: repository path inside the container.
- `status`: `pending`, `ready`, `running`, `stopped`, or `error`.

State transitions:
- `pending -> ready` after image lookup and `git checkout` to the task base
  commit succeed.
- `ready -> running` when the agent starts tool execution.
- `running -> stopped | error` when the run ends or the container fails.

Validation:
- A new task container must run `git checkout <base_commit>` before the first
  model action.
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
- The summary must include base image, official-compatible marker, validation
  command source, repo path, base commit, and validation mode for inspection.
- If the sandbox fails after agent execution begins, partial trajectory,
  summary error, sandbox metadata, and any derivable patch/prediction artifacts
  are required.

## ContainerToolResult

Uses the existing ToolExecutionResult shape with container-specific execution
details in bounded output metadata.

Validation:
- `read_file`, `write_file`, and `search_code` paths resolve under
  `repo_path` inside the selected container.
- `run_tests` executes inside the selected container and records stdout/stderr
  summaries using the existing TestResult rules.
