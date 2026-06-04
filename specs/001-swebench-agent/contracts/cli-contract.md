# CLI Contract: SWE-Bench Lite Coding Agent

## Command: `coding-agent run`

Runs one AgentRun against a prepared local workspace.

Required arguments:
- `--instance-id <id>`
- `--workspace <path>`
- `--problem-statement-file <path>`
- `--allowed-test <command>`; repeatable, at least one required
- `--max-steps <int>`
- `--timeout-seconds <int>`
- `--test-timeout-seconds <int>`
- `--output-dir <path>`

Optional arguments:
- `--model <name>` defaults to configured model name.
- `--backend <openai-compatible|mock>` defaults to `openai-compatible`.

Environment variables for `--backend openai-compatible`:
- `PROVIDER`: provider label recorded in run metadata.
- `MODEL`: model name used for the run when `--model` is omitted.
- `API_KEY`: API credential for the compatible endpoint.
- `BASE_URL`: OpenAI-compatible API base URL.

Outputs:
- `<output-dir>/trajectory.jsonl`
- `<output-dir>/final.patch`
- `<output-dir>/summary.json`
- `<output-dir>/prediction.jsonl`

Exit statuses:
- `0`: run completed and produced all artifacts, regardless of solved/failed
  benchmark outcome.
- `2`: invalid input, missing workspace, missing problem statement, missing
  budget, missing allowed test command, or missing required model environment
  variable.
- `3`: trajectory or artifact persistence failed.
- `4`: unexpected agent runtime error.

Rules:
- All file paths passed to tools must stay inside `--workspace`.
- `run_tests` may execute only commands declared through `--allowed-test`.
- `write_file` writes complete file content only.
- Budget stops are recorded in `trajectory.jsonl` and `summary.json`.
- OpenAI-compatible backend responses are parsed into the same AgentAction
  schema used by the mock backend.

## Command: `coding-agent inspect`

Displays a concise run report from an existing output directory.

Required arguments:
- `--run-dir <path>`

Reads:
- `summary.json`
- `trajectory.jsonl`

Output:
- Final status.
- Changed files.
- Last successful tool call.
- Error point or budget stop if present.

Exit statuses:
- `0`: report printed.
- `2`: run directory or required artifacts missing.

## Command: `coding-agent export-prediction`

Recreates a SWE-Bench-compatible prediction JSONL from a run directory.

Required arguments:
- `--run-dir <path>`
- `--model-name <name>`
- `--output <path>`

Output JSONL schema:

```json
{"instance_id":"<id>","model_name_or_path":"<model>","model_patch":"<patch text>"}
```

Exit statuses:
- `0`: prediction written.
- `2`: missing summary or final patch.
- `3`: output write failed.
