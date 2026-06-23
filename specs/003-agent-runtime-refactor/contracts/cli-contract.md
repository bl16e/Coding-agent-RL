# CLI Contract: Agent Runtime Environment Refactor

This contract describes user-visible command behavior for the first version of
the refactored benchmark runtime. The first version exposes only `prepare` and
`run` for SWE-Bench benchmark runtime work.

## Exit Code Contract

- `0`: command completed.
- `2`: user input, dataset, unsupported repository, missing metadata, missing
  image without opt-in build, validation-source, or configuration error before
  agent execution.
- `3`: artifact persistence failure.
- `4`: runtime, image build, sandbox, or model execution failure after the
  relevant operation has started.

## `coding-agent swebench prepare`

Prepare all required runtime layers and create a running prepared task
environment for a later `run`.

```text
coding-agent swebench prepare
  --dataset <path>
  --instance-id <id>
  --output-dir <path>
  [--build-missing]
  [--replace-existing]
  [--arch <x86_64|arm64>]
```

**Behavior**

- Loads the selected task record from the dataset.
- Rejects unknown repositories before image checks.
- Rejects supported repositories missing source-backed metadata before image
  checks.
- Resolves the adapted task spec and base/env/instance image keys.
- Without `--build-missing`, reports missing images and exits before building.
- With `--build-missing`, builds missing images in base -> env -> instance
  order and reuses existing images.
- Uses official-style runtime image resolution.
- Does not accept `--registry`.
- Creates the task-specific prepared environment from the instance image; image
  layers may be reused, but already-used task workspaces are not reused.
- Records the prepared environment in `.coding-agent/active-sandboxes.json`.
- Writes `sandbox.json` in the output directory.
- Leaves the prepared environment running for `run`.
- Fails before environment changes when an active entry already exists for the
  selected instance and `--replace-existing` is absent.
- With `--replace-existing`, stops or removes the prior prepared environment
  when present, replaces the active index entry, writes new preparation
  metadata, and does not modify prior run artifact directories.
- Does not choose final validation mode; regression validation is selected only
  by `run --include-pass-to-pass`.
- Fails before agent execution on unsupported repository, missing
  source-backed metadata, or missing image without `--build-missing`.

## `coding-agent swebench run`

Solve one selected task by using an active prepared task environment.

```text
coding-agent swebench run
  --dataset <path>
  --instance-id <id>
  --max-steps <n>
  --timeout-seconds <n>
  --test-timeout-seconds <n>
  --output-dir <path>
  [--include-pass-to-pass]
  [--cleanup]
  [--model <name>]
  [--backend <mock|openai-compatible>]
```

**Behavior**

- Does not accept `--registry`.
- Uses the official-style runtime path by default.
- Loads `.coding-agent/active-sandboxes.json`.
- Validates active environment instance id and base revision against the
  dataset record.
- Does not create or build images.
- Fails before agent execution when the prepared environment is missing or
  mismatched.
- Accepts only a `ready` prepared environment. Entries marked `used`, `stopped`,
  `error`, or `running` fail before agent execution and direct the developer to
  run `prepare --replace-existing`.
- Runs the host-owned agent with repository tools confined to the prepared
  task environment.
- Transitions the environment from `ready` to `running`, then to `used` for
  completed or limit-exhausted runs. Post-start runtime failures record `error`
  while preserving partial artifacts.
- Uses default `FAIL_TO_PASS` validation unless `--include-pass-to-pass` is
  supplied for this run.
- Runs final validation by executing the adapted TestSpec `eval_script` inside
  the prepared environment and records official-style grading.
- Writes `trajectory.jsonl`, `trajectory.json`, `summary.json`, `final.patch`,
  `prediction.jsonl`, and `sandbox.json`.
- Without `--cleanup`, retains the active index entry with status `used`.
- With `--cleanup`, records `used -> stopped` for completed or limit-exhausted
  runs, stops or removes the container, and removes the entry from
  `.coding-agent/active-sandboxes.json`.
- With `--cleanup` after a post-start runtime failure, records `running -> error`
  plus the cleanup action, stops or removes the container when possible, and
  removes the active index entry.

## Unsupported Inputs

Commands must fail before agent execution with exit code 2 for:

- dataset file missing or unreadable;
- selected instance id missing;
- repository outside the supported core SWE-Bench Lite set;
- supported repository/version missing source-backed metadata;
- prepare required image missing and `--build-missing` absent;
- prepare active entry already exists and `--replace-existing` absent;
- validation metadata unavailable or untranslatable;
- run active environment missing or mismatched;
- run active environment status is `used`, `stopped`, `error`, or `running`;
- legacy registry, legacy sandbox, or legacy SWE-Bench runtime options such as
  `--registry`, `prepare-sandbox`, `solve-sandbox`, `prepare-sandboxes`, or
  `solve-sandboxes`;
- batch benchmark orchestration request.

## Artifact Contract

For every run that reaches agent execution:

- `summary.json` records official-style runtime path, image lineage,
  prepared-environment status transition, validation source, validation mode,
  final outcome, and artifact locations.
- `sandbox.json` records task identity, repository, version, base revision,
  container name, repo path, base/env/instance image keys, build policy,
  built/reused images, readiness checks, prepared-environment status, cleanup
  action, active-index result, and validation source.
- `summary.json` and `sandbox.json` are sufficient for run review without
  reading `.coding-agent/active-sandboxes.json` or any legacy registry.
- `final.patch` excludes validation-only task files and patches.
- `prediction.jsonl` uses the exported final patch.
