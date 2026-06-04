# Data Model: SWE-Bench Lite Coding Agent

## BenchmarkTask

- `instance_id`: unique SWE-Bench task identifier.
- `workspace`: absolute path to prepared local repository workspace.
- `problem_statement`: issue text or path-loaded problem statement content.
- `repo`: optional upstream repository identifier.
- `base_commit`: optional commit hash for traceability.
- `allowed_test_commands`: non-empty ordered set of commands allowed for
  `run_tests`.

Validation:
- `instance_id`, `workspace`, `problem_statement`, and at least one allowed test
  command are required.
- `workspace` must exist and be a directory.

## RunBudget

- `max_steps`: positive integer.
- `timeout_seconds`: positive integer total run budget.
- `test_timeout_seconds`: positive integer budget for each test command.

Validation:
- All three values are required before an AgentRun starts.

## ModelConfig

- `provider`: model provider identifier loaded from `PROVIDER`.
- `model`: model name loaded from `MODEL`.
- `api_key`: API credential loaded from `API_KEY`.
- `base_url`: OpenAI-compatible endpoint loaded from `BASE_URL`.

Validation:
- OpenAI-compatible runs require all four environment variables.
- Missing or empty model environment variables are reported as invalid run
  configuration before an AgentRun starts.

## AgentRun

- `run_id`: unique run identifier.
- `task`: BenchmarkTask.
- `budget`: RunBudget.
- `model_config`: ModelConfig used for non-mock runs.
- `model_name`: model identifier used for the run.
- `status`: `pending`, `running`, `solved`, `failed`, `incomplete`, or
  `errored`.
- `started_at`, `ended_at`: timestamps.
- `output_dir`: directory for run artifacts.

State transitions:
- `pending -> running`
- `running -> solved | failed | incomplete | errored`
- Terminal states do not transition.

## TrajectoryStep

- `step_index`: monotonically increasing integer.
- `timestamp`: step timestamp.
- `action_type`: `model`, `tool_call`, `tool_result`, `final`, or `error`.
- `reasoning_summary`: concise decision summary; required for agent decision
  steps and optional for tool result, final, and error steps.
- `next_intent`: intended next action; required for agent decision steps and
  optional for tool result, final, and error steps.
- `tool_selection_reason`: reason for selected tool when applicable; required
  when an agent decision chooses a tool.
- `tool_call`: optional ToolCall reference.
- `outcome`: `ok`, `rejected`, `failed`, `timeout`, or `error`.

Validation:
- Every persisted step requires `step_index`, `action_type`, and `outcome`.
- Completed runs require a reasoning summary and next intent for every agent
  decision step.

## ToolCall

- `tool_name`: `read_file`, `write_file`, `search_code`, or `run_tests`.
- `input`: JSON-serializable tool input.
- `output_summary`: bounded output summary.
- `status`: `ok`, `rejected`, `failed`, `timeout`, or `error`.
- `started_at`, `ended_at`: timestamps.

Validation:
- `tool_name` must be one of the four supported tools.
- Tool paths must resolve inside the task workspace.

## FileModification

- `path`: workspace-relative path.
- `write_status`: `ok`, `rejected`, or `error`.
- `before_hash`: content hash before write when available.
- `after_hash`: content hash after write when successful.

Validation:
- `write_file` accepts complete file content only.
- Final patch generation uses before-and-after file states.

## TestResult

- `command`: executed allowed test command.
- `status`: `passed`, `failed`, `timeout`, `execution_error`, or `rejected`.
- `exit_code`: optional process exit code.
- `duration_seconds`: elapsed time.
- `output_summary`: bounded stdout/stderr summary.

Validation:
- Commands not present in `allowed_test_commands` are rejected and recorded.

## RunSummary

- `run_id`, `instance_id`, `model_name`, `status`.
- `budget`: RunBudget snapshot.
- `changed_files`: list of modified paths.
- `test_summary`: counts by TestResult status.
- `error`: optional error description.
- `artifacts`: paths to `trajectory.jsonl`, `final.patch`, and
  `prediction.jsonl`.

`summary.json` is the file representation of RunSummary.

## Prediction

- `instance_id`: SWE-Bench instance id.
- `model_name_or_path`: model name used for the run.
- `model_patch`: final patch text.

Validation:
- Exported as JSONL with one prediction object per line.
