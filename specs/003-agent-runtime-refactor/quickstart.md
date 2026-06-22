# Quickstart: Agent Runtime Environment Refactor

This guide validates the planned behavior after implementation. Commands are
written for PowerShell from the repository root.

## Prerequisites

- Development dependencies installed:

```powershell
python -m pip install -e .[dev]
```

- A local SWE-Bench Lite parquet dataset containing at least one task from the
  supported core repository set.
- Docker available for manual runtime checks. Automated fake-Docker tests do
  not require a real Docker daemon.

## 1. Run Contract Tests

```powershell
python -m pytest tests\contract\test_cli_swebench_run_contract.py -q
python -m pytest tests\contract\test_cli_swebench_runtime_contract.py -q
```

Expected:

- `swebench run` no longer requires `--registry`.
- `prepare` and `run` parse required arguments.
- Legacy registry commands still parse as explicit compatibility flows.

## 2. Run Unit Tests For Runtime Metadata

```powershell
python -m pytest `
  tests\unit\test_swebench_testspec.py `
  tests\unit\test_swebench_repo_specs.py `
  tests\unit\test_swebench_script_builders.py `
  tests\unit\test_swebench_images.py `
  tests\unit\test_swebench_grading.py `
  tests\unit\test_container_tools.py `
  tests\unit\test_sandbox_manager.py -q
```

Expected:

- Adapted task specs derive deterministic image keys.
- Unknown repositories and missing source-backed metadata fail before agent
  execution.
- Image build planning checks images before building and builds base -> env ->
  instance only with explicit opt-in.
- Validation-only test patches are applied temporarily or excluded from final
  patch export.

## 3. Validate Prepare Without Building

```powershell
coding-agent swebench prepare `
  --dataset data\lite.parquet `
  --instance-id django__django-11099 `
  --output-dir runs\prepare-check
```

Expected when images are missing:

- Command exits before agent execution.
- Message identifies missing image keys.
- No model backend is initialized.
- `runs\prepare-check` contains preparation diagnostics if the output directory
  was created before the failure.

## 4. Validate Prepare With Explicit Build

```powershell
coding-agent swebench prepare `
  --dataset data\lite.parquet `
  --instance-id django__django-11099 `
  --build-missing `
  --output-dir runs\django-11099-prepare
```

Expected:

- Missing images are built in base -> env -> instance order.
- Existing images are reused.
- `sandbox.json` records built and reused image keys.
- Active environment index includes the selected instance id.
- Readiness checks are recorded.
- No agent solving starts.

## 5. Run Agent From Prepared Environment

```powershell
coding-agent swebench run `
  --dataset data\lite.parquet `
  --instance-id django__django-11099 `
  --backend mock `
  --max-steps 1 `
  --timeout-seconds 60 `
  --test-timeout-seconds 30 `
  --output-dir runs\django-11099-run `
  --cleanup
```

Expected:

- Standard artifacts are written.
- `summary.json` and `sandbox.json` identify the official-style runtime path.
- Final review executes the adapted TestSpec `eval_script` and records graded
  `FAIL_TO_PASS` plus selected `PASS_TO_PASS` results.
- The final patch excludes validation-only test patch changes.
- The prepared environment is removed only because `--cleanup` was provided.

## 6. Run Without Prepared Environment

```powershell
coding-agent swebench run `
  --dataset data\lite.parquet `
  --instance-id django__django-11099 `
  --backend mock `
  --max-steps 1 `
  --timeout-seconds 60 `
  --test-timeout-seconds 30 `
  --output-dir runs\django-11099-missing
```

Expected:

- Command exits before agent execution.
- Error identifies that the prepared environment is missing or mismatched.
- No model calls occur.

## 7. Unsupported Repository Check

Run a task whose repo is outside the supported core SWE-Bench Lite repository
set.

Expected:

- Command exits with code 2 before agent execution.
- Error identifies the repository as unsupported.
- No model calls occur.

## 8. Missing Source-Backed Metadata Check

Run a task inside the supported repository set but with a repo/version that has
no source-backed metadata.

Expected:

- Command exits with code 2 before agent execution.
- Error identifies which metadata source is missing.
- No fixture-only metadata is used.

## 9. Legacy Compatibility Check

```powershell
coding-agent sandbox list --registry .coding-agent\sandboxes.json
```

Expected:

- Legacy command remains available.
- New benchmark run commands do not require or read this registry unless an
  explicit compatibility command is used.

## 10. Full Verification

```powershell
python -m pytest tests\unit -q
python -m pytest tests\contract -q
python -m pytest tests\integration -q
python -m pytest -q
```

Expected:

- Unit, contract, and integration tests pass.
- Real Docker checks remain opt-in/manual unless explicitly marked for the
  local environment.
