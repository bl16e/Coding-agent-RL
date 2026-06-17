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

## `coding-agent swebench prepare-runtime`

Prepare required runtime image layers for selected supported tasks.

```text
coding-agent swebench prepare-runtime
  --dataset <path>
  (--instance-id <id> | --instance-id-file <path>)
  [--build-missing]
  [--arch <x86_64|arm64>]
  [--output-dir <path>]
```

**Behavior**

- Loads selected task records from the dataset.
- Rejects unknown repositories before image checks.
- Rejects supported repositories missing source-backed metadata before image
  checks.
- Resolves adapted task specs and image keys.
- Without `--build-missing`, reports missing images and exits before building.
- With `--build-missing`, builds missing images in base -> env -> instance
  order and reuses existing images.
- Writes a runtime preparation report when `--output-dir` is provided.
- Does not start the model.
- Does not perform batch benchmark solving.

## `coding-agent swebench prepare`

Create and index a running prepared task environment for later continuation.

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

- Uses official-style runtime image resolution.
- Does not require `--registry`.
- Creates or verifies the task-specific prepared environment.
- Records the prepared environment in `.coding-agent/active-sandboxes.json`.
- Writes `sandbox.json` in the output directory.
- Leaves the prepared environment running for continue-prepared.
- Fails before agent execution on unsupported repository, missing
  source-backed metadata, or missing image without `--build-missing`.

## `coding-agent swebench run`

Prepare and solve one selected task in one workflow.

```text
coding-agent swebench run
  --dataset <path>
  --instance-id <id>
  --max-steps <n>
  --timeout-seconds <n>
  --test-timeout-seconds <n>
  --output-dir <path>
  [--build-missing]
  [--include-pass-to-pass]
  [--model <name>]
  [--backend <mock|openai-compatible>]
  [--arch <x86_64|arm64>]
```

**Behavior**

- Does not require `--registry`.
- Uses the official-style runtime path by default.
- Prepares the runtime environment when necessary.
- Runs the host-owned agent with repository tools confined to the prepared
  task environment.
- Runs final official-style validation and records grading.
- Writes `trajectory.jsonl`, `trajectory.json`, `summary.json`, `final.patch`,
  `prediction.jsonl`, and `sandbox.json`.
- Cleans up the task environment unless a later design explicitly exposes a
  keep-running option.

## `coding-agent swebench continue-prepared`

Solve using an active prepared task environment.

```text
coding-agent swebench continue-prepared
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

- Loads `.coding-agent/active-sandboxes.json`.
- Validates active environment instance id and base revision against the
  dataset record.
- Does not create or build images.
- Runs the host-owned agent against the active prepared environment.
- Writes the standard artifact set plus runtime metadata.
- Removes the environment only when `--cleanup` is provided.

## Legacy Compatibility Commands

Existing `coding-agent sandbox register`, `coding-agent sandbox list`, and
legacy SWE-Bench commands may remain as explicit compatibility flows. They must
be labeled as compatibility behavior in help text and artifacts when used.
New benchmark `prepare-runtime`, `prepare`, `run`, and `continue-prepared`
commands must not silently use the legacy registry.

## Unsupported Inputs

Commands must fail before agent execution with exit code 2 for:

- dataset file missing or unreadable;
- selected instance id missing;
- repository outside the supported core SWE-Bench Lite set;
- supported repository/version missing source-backed metadata;
- required image missing and `--build-missing` absent;
- validation metadata unavailable or untranslatable;
- continue-prepared active environment mismatch;
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
