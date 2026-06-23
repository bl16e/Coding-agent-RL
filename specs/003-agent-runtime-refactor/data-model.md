# Data Model: Agent Runtime Environment Refactor

## BenchmarkTaskRecord

Represents one selected dataset row after input normalization.

**Fields**

- `instance_id`: unique benchmark task id.
- `repo`: upstream repository id.
- `version`: source-backed repo/version grouping; required for new benchmark
  runtime support.
- `base_commit`: starting revision for the task.
- `problem_statement`: task prompt.
- `fail_to_pass`: fix-verification identifiers; non-empty.
- `pass_to_pass`: optional regression identifiers.
- `test_patch`: optional validation-only patch.
- `environment_setup_commit`: optional upstream metadata.
- `eval_script`: optional dataset-provided source-backed eval script.

**Validation Rules**

- `instance_id`, `repo`, `base_commit`, `problem_statement`, and
  `fail_to_pass` are required.
- `repo` must be in the supported core SWE-Bench Lite repository set.
- `repo` + `version` must resolve to source-backed repo metadata.
- Missing source-backed metadata fails before agent execution.

## RepoVersionSpec

Source-backed metadata for a supported repository/version.

**Fields**

- `repo`: repository id.
- `version`: repo/version key.
- `language`: official harness language extension key.
- `python_version` or runtime equivalent: language runtime version when
  applicable.
- `packages`: source-backed environment package metadata.
- `pip_packages`: optional package list.
- `install_commands`: source-backed repository setup commands.
- `test_command`: source-backed base validation command.
- `docker_specs`: optional source-backed Docker spec overrides.
- `source_reference`: local upstream, official sample, or existing contract
  reference proving the metadata source.
- `review_status`: `source_backed`, `unsupported`, or `needs_review`.

**Validation Rules**

- Production metadata entries require `source_reference`.
- Entries marked `unsupported` must produce pre-agent input errors.
- Test-only fixture entries must not be used by production lookup paths unless
  they are also source-backed.

## AdaptedTestSpec

Internal source-backed task spec used as the runtime contract.

**Fields**

- `instance_id`
- `repo`
- `version`
- `base_commit`
- `repo_path`
- `env_name`
- `fail_to_pass`
- `pass_to_pass`
- `test_patch`
- `repo_script`
- `env_script`
- `eval_script`
- `language`
- `arch`
- `platform`
- `base_image_key`
- `env_image_key`
- `instance_image_key`
- `repo_version_source`

**Relationships**

- Created from one `BenchmarkTaskRecord`.
- Requires one source-backed `RepoVersionSpec`.
- Produces one `RuntimeLineage`.
- Produces one `ValidationSet`.

**Validation Rules**

- Image keys must be deterministic for the same spec inputs.
- `env_image_key` changes when environment setup script or Docker specs change.
- `instance_image_key` is task-specific.
- `repo_script`, `env_script`, and `eval_script` must derive from
  source-backed metadata.

## RuntimeLineage

Audit record for reusable and task-specific runtime layers.

**Fields**

- `runtime_path`: `official_style`.
- `base_image_key`
- `env_image_key`
- `instance_image_key`
- `platform`
- `build_missing`: boolean.
- `built_images`: ordered list of images built during this command.
- `reused_images`: ordered list of images already present.
- `metadata_sources`: source references used to derive scripts and image keys.

**Validation Rules**

- New benchmark runs must use `official_style`.
- Legacy registry lineage is not valid for this feature's benchmark runtime.
- Missing images without `build_missing` fail before agent execution.

## PreparedTaskEnvironment

Running or prepared task-specific environment for one selected task.

**Fields**

- `instance_id`
- `repo`
- `version`
- `base_commit`
- `container_name`
- `repo_path`
- `runtime_lineage`
- `status`: `pending`, `ready`, `running`, `used`, `stopped`, or `error`.
- `ready_checks`
- `sandbox_json`

**State Transitions**

```text
pending -> ready -> running -> used
pending -> error
ready -> error
running -> error
used -> stopped
```

**Validation Rules**

- Ready environments must pass container exec, git worktree, base revision,
  clean workspace, task identity, and validation source checks.
- `run` must reject instance/base-commit mismatches.
- `run` may consume only `ready` environments. `used`, `stopped`, `error`, and
  `running` states are rejected before agent execution.
- `run` transitions `ready -> running -> used` for completed or limit-exhausted
  agent runs. Runtime failures after agent execution starts transition
  `running -> error`.
- Reusing a used, stopped, errored, or concurrently running prepared environment
  requires a fresh `prepare --replace-existing`.

## ValidationSet

Allowed in-run validation commands, final review script, and source metadata.

**Fields**

- `fail_to_pass`
- `pass_to_pass`
- `include_pass_to_pass`: run-time selection from
  `run --include-pass-to-pass`.
- `command_source`: `official_testspec` or `source_backed_repo_spec`.
- `eval_script`: adapted TestSpec official-style final review script.
- `allowed_commands`: commands the agent may request during the run.
- `test_patch_reset_commands`

**Validation Rules**

- `fail_to_pass` is required.
- `pass_to_pass` is included only when explicitly requested for a run.
- Requests outside `allowed_commands` are rejected and recorded during the run.
- Final benchmark review must execute `eval_script`; `allowed_commands` are not
  sufficient to declare the final benchmark outcome.
- Validation-only patches must not appear in the final exported code patch.

## EvalReport

Final validation outcome parsed from the adapted TestSpec `eval_script` output.

**Fields**

- `resolved`
- `fail_to_pass_success`
- `fail_to_pass_failure`
- `pass_to_pass_success`
- `pass_to_pass_failure`
- `raw_output_artifact`

**Validation Rules**

- A task is resolved only when all required `FAIL_TO_PASS` checks pass and all
  selected `PASS_TO_PASS` checks pass.
- Missing or unparsable `eval_script` output is recorded as validation failure,
  not as a solved task.

## AgentRunArtifactSet

The persisted artifacts for one run.

**Fields**

- `trajectory.jsonl`
- `trajectory.json`
- `summary.json`
- `final.patch`
- `prediction.jsonl`
- `sandbox.json`

**Validation Rules**

- Runs that reach agent execution preserve the core artifact set.
- Post-start runtime failures preserve partial diagnostics where derivable.
- `summary.json` and `sandbox.json` identify runtime path, task metadata,
  image lineage, prepared-environment status transition, validation source,
  selected validation mode, cleanup action, active-index result, and artifact
  locations.

## ActivePreparedEnvironmentIndex

Index of prepared environments available for `run` workflows.

**Fields**

- `instance_id`
- `container_name`
- `repo`
- `version`
- `base_commit`
- `sandbox_json`
- `runtime_lineage`
- `status`

**Validation Rules**

- Duplicate active entries are rejected unless replace semantics are explicit.
- `run` validates index metadata against the requested task record.
- Without `--replace-existing`, `prepare` rejects an existing entry for the same
  instance before changing containers or index state.
- With `--replace-existing`, `prepare` stops or removes the prior prepared
  environment when present, replaces the active index entry, and does not modify
  prior run artifact directories.
- Completed or limit-exhausted `run` without `--cleanup` retains the active
  entry as `used`.
- Completed or limit-exhausted `run --cleanup` records `used -> stopped` in run
  artifacts, stops or removes the container, and removes the active index entry.
- Post-start runtime failures without `--cleanup` retain or update the active
  index entry as `error` so a later run rejects it before agent execution.
- Post-start runtime failures with `--cleanup` record `running -> error` plus
  the cleanup action in run artifacts, stop or remove the container when
  possible, and remove the active index entry.
- Active index status is not a review dependency: completed or failed run
  inspection uses run-level `summary.json` and `sandbox.json`.

## UnsupportedLegacyOperation

Prior SWE-Bench runtime entry point that is no longer supported by this
feature.

**Fields**

- `operation_name`
- `legacy_surface`: `registry_option`, `sandbox_command`, or `batch_command`.
- `replacement`: `prepare` or `run` when a direct replacement exists.
- `error_message`

**Validation Rules**

- Legacy operations are rejected before agent execution.
- New benchmark runs must not silently use legacy registry data.
- Help text and argument errors must direct users to `prepare` and `run`.
