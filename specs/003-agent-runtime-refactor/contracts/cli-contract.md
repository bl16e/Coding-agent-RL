# CLI Contract: Agent Runtime Environment Refactor

This contract describes user-visible command behavior for the first version of
the refactored benchmark runtime. Names are documented as target contracts for
planning; implementation may preserve old aliases only as explicit
compatibility commands.

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
  [--include-pass-to-pass]
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
- Does not require `--registry`.
- Creates or verifies the task-specific prepared environment.
- Records the prepared environment in `.coding-agent/active-sandboxes.json`.
- Writes `sandbox.json` in the output directory.
- Leaves the prepared environment running for `run`.
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

- Does not require `--registry`.
- Uses the official-style runtime path by default.
- Loads `.coding-agent/active-sandboxes.json`.
- Validates active environment instance id and base revision against the
  dataset record.
- Does not create or build images.
- Fails before agent execution when the prepared environment is missing or
  mismatched.
- Runs the host-owned agent with repository tools confined to the prepared
  task environment.
- Runs final validation by executing the adapted TestSpec `eval_script` inside
  the prepared environment and records official-style grading.
- Writes `trajectory.jsonl`, `trajectory.json`, `summary.json`, `final.patch`,
  `prediction.jsonl`, and `sandbox.json`.
- Removes the environment only when `--cleanup` is provided.

## Legacy Compatibility Commands

Existing `coding-agent sandbox register`, `coding-agent sandbox list`, and
legacy SWE-Bench commands may remain as explicit compatibility flows. They must
be labeled as compatibility behavior in help text and artifacts when used.
New benchmark `prepare` and `run` commands must not silently use the legacy
registry.

## Unsupported Inputs

Commands must fail before agent execution with exit code 2 for:

- dataset file missing or unreadable;
- selected instance id missing;
- repository outside the supported core SWE-Bench Lite set;
- supported repository/version missing source-backed metadata;
- prepare required image missing and `--build-missing` absent;
- validation metadata unavailable or untranslatable;
- run active environment missing or mismatched;
- batch benchmark orchestration request for this feature's new runtime path.

## Artifact Contract

For every run that reaches agent execution:

- `summary.json` records runtime path, image lineage, validation source,
  validation mode, final outcome, and artifact locations.
- `sandbox.json` records task identity, repository, version, base revision,
  container name, repo path, base/env/instance image keys, build policy,
  built/reused images, readiness checks, and validation source.
- `final.patch` excludes validation-only task files and patches.
- `prediction.jsonl` uses the exported final patch.
