# Stage 1/2 Boundary Tightening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stage 1 local-vLLM SWE-Bench Lite evaluation and Stage 2 teacher-API SWE-smith trajectory generation explicit, stage-isolated workflows, while removing supported positive legacy SWE-Bench sandbox/registry paths.

**Architecture:** Add stage-specific model configuration on top of the existing OpenAI-compatible backend, then add `stage1` and `stage2` CLI groups that delegate to the existing official SWE-Bench batch runner and SWE-smith helpers. Update scripts and docs to use the new stage entry points, and delete legacy positive SWE-Bench runtime helpers/tests while keeping explicit unsupported-operation rejection.

**Tech Stack:** Python 3.11, argparse, pytest, existing `coding_agent` CLI/library, shell scripts, Docker CLI through existing wrappers, fake-backed tests.

---

## File Structure

- Modify `src/coding_agent/model_backends/openai_compatible.py`
  - Add `load_stage_model_config(stage, ...)` and stage-specific env key mapping.
  - Keep `load_model_config()` behavior unchanged for lower-level generic commands.
- Modify `tests/unit/test_openai_compatible_config.py`
  - Add stage env tests proving no fallback to generic or opposite-stage env.
- Modify `src/coding_agent/cli.py`
  - Remove unused legacy SWE-Bench positive imports and handlers.
  - Add `stage1 run-qwen-vllm`.
  - Add `stage2 generate-teacher-trajectories`.
  - Use stage-specific config loaders in stage commands.
- Create `tests/contract/test_cli_stage_workflows.py`
  - Cover Stage 1/2 command parsing, env isolation, dispatch, and missing config.
- Modify `src/coding_agent/swebench/sandbox_run.py`
  - Remove legacy positive helpers or quarantine only if absolutely required by non-runtime code.
  - Keep official runtime helpers: `prepare_official_swebench_runtime`, `run_prepared_swebench_runtime`, `run_official_swebench_batch`.
  - Keep shared helpers that official runtime still imports or tests require.
- Delete or rewrite legacy positive tests:
  - Delete `tests/integration/test_swebench_sandbox_run.py`.
  - Delete `tests/integration/test_swebench_batch_run.py` tests that call legacy `run_swebench_tasks`, `prepare_swebench_sandboxes`, `solve_swebench_sandboxes`.
  - Delete `tests/integration/test_sandbox_reuse.py` if it only covers legacy `run_swebench_task`.
  - Delete `tests/integration/test_swebench_validation_integration.py` if it only covers legacy registry-template validation.
  - Keep contract tests that assert legacy commands are rejected.
- Modify `tests/contract/test_cli_swebench_runtime_contract.py`
  - Adjust help expectations if stage entry points become primary.
  - Keep rejection tests for `prepare-sandbox`, `solve-sandbox`, `prepare-sandboxes`, `solve-sandboxes`, and `--registry`.
- Modify `scripts/deploy.sh`
  - Retarget from “SWE-smith SFT Pipeline Deployment” to Stage 1/2 bootstrap.
  - Generate `.env.stage1.example` and `.env.stage2.example`.
  - Keep generic `.env` as lower-level compatibility only.
  - Print next steps for `scripts/run_stage1_qwen_vllm.sh` and `scripts/run_stage2_teacher_trajectories.sh`.
- Create `scripts/run_stage1_qwen_vllm.sh`
  - Validate `STAGE1_*`, activate venv, and call `coding-agent stage1 run-qwen-vllm`.
- Create `scripts/run_stage2_teacher_trajectories.sh`
  - Validate `STAGE2_*`, activate venv, create/reuse subset, and call `coding-agent stage2 generate-teacher-trajectories`.
- Modify `scripts/run_sft_pipeline.sh`
  - Convert to a compatibility wrapper that warns and calls the Stage 2 script.
- Modify docs:
  - `README.md`
  - `docs/cost_optimized_two_stage_deployment.md`
  - `docs/swesmith_sft_pipeline_guide.md`
  - Leave unrelated user-modified `docs/training_stage3_stage4_roadmap_zh.md` untouched unless explicitly requested.

---

### Task 1: Add Stage-Specific Model Config Loader

**Files:**
- Modify: `src/coding_agent/model_backends/openai_compatible.py`
- Test: `tests/unit/test_openai_compatible_config.py`

- [ ] **Step 1: Write failing tests for Stage 1 config**

Append these tests to `tests/unit/test_openai_compatible_config.py`:

```python
def test_load_stage_model_config_reads_stage1_values(tmp_path: Path):
    from coding_agent.model_backends.openai_compatible import load_stage_model_config

    config = load_stage_model_config(
        "stage1",
        env={
            "STAGE1_PROVIDER": "openai",
            "STAGE1_MODEL": "qwen2.5-coder-7b",
            "STAGE1_API_KEY": "not-needed",
            "STAGE1_BASE_URL": "http://vllm:8000/v1",
            "PROVIDER": "generic-provider",
            "MODEL": "generic-model",
            "API_KEY": "generic-key",
            "BASE_URL": "http://generic",
        },
        dotenv_path=tmp_path / ".env",
    )

    assert config.provider == "openai"
    assert config.model == "qwen2.5-coder-7b"
    assert config.api_key == "not-needed"
    assert config.base_url == "http://vllm:8000/v1"


def test_load_stage_model_config_does_not_fallback_to_generic_env(tmp_path: Path):
    from coding_agent.model_backends.openai_compatible import load_stage_model_config

    with pytest.raises(MissingModelConfigError) as exc_info:
        load_stage_model_config(
            "stage1",
            env={
                "PROVIDER": "generic-provider",
                "MODEL": "generic-model",
                "API_KEY": "generic-key",
                "BASE_URL": "http://generic",
            },
            dotenv_path=tmp_path / ".env",
        )

    assert exc_info.value.missing_keys == (
        "STAGE1_PROVIDER",
        "STAGE1_MODEL",
        "STAGE1_API_KEY",
        "STAGE1_BASE_URL",
    )


def test_load_stage_model_config_model_override_only_replaces_stage_model(tmp_path: Path):
    from coding_agent.model_backends.openai_compatible import load_stage_model_config

    config = load_stage_model_config(
        "stage2",
        env={
            "STAGE2_PROVIDER": "openai",
            "STAGE2_MODEL": "teacher-default",
            "STAGE2_API_KEY": "teacher-key",
            "STAGE2_BASE_URL": "https://teacher.example/v1",
        },
        dotenv_path=tmp_path / ".env",
        model_override="teacher-override",
    )

    assert config.provider == "openai"
    assert config.model == "teacher-override"
    assert config.api_key == "teacher-key"
    assert config.base_url == "https://teacher.example/v1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/unit/test_openai_compatible_config.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` for `load_stage_model_config`.

- [ ] **Step 3: Implement stage loader**

In `src/coding_agent/model_backends/openai_compatible.py`, add this near `REQUIRED_ENV_KEYS`:

```python
STAGE_ENV_KEYS = {
    "stage1": ("STAGE1_PROVIDER", "STAGE1_MODEL", "STAGE1_API_KEY", "STAGE1_BASE_URL"),
    "stage2": ("STAGE2_PROVIDER", "STAGE2_MODEL", "STAGE2_API_KEY", "STAGE2_BASE_URL"),
}
```

Add this function after `load_model_config()`:

```python
def load_stage_model_config(
    stage: str,
    env: dict[str, str] | None = None,
    dotenv_path: Path | str = ".env",
    model_override: str | None = None,
) -> ModelConfig:
    """Load model settings from stage-specific environment variables only."""

    try:
        provider_key, model_key, api_key_key, base_url_key = STAGE_ENV_KEYS[stage]
    except KeyError as exc:
        raise ValueError(f"unknown stage model config: {stage}") from exc

    file_values = parse_dotenv(Path(dotenv_path))
    env_values = dict(os.environ if env is None else env)
    stage_keys = (provider_key, model_key, api_key_key, base_url_key)
    merged = {key: file_values.get(key, "") for key in stage_keys}
    merged.update({key: env_values[key] for key in stage_keys if env_values.get(key)})
    if model_override:
        merged[model_key] = model_override

    missing = tuple(key for key in stage_keys if not merged.get(key))
    if missing:
        raise MissingModelConfigError(missing)
    return ModelConfig(
        provider=merged[provider_key],
        model=merged[model_key],
        api_key=merged[api_key_key],
        base_url=merged[base_url_key],
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python -m pytest tests/unit/test_openai_compatible_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/model_backends/openai_compatible.py tests/unit/test_openai_compatible_config.py
git commit -m "feat: add stage model config loader"
```

---

### Task 2: Add Stage 1 CLI Workflow

**Files:**
- Modify: `src/coding_agent/cli.py`
- Create: `tests/contract/test_cli_stage_workflows.py`

- [ ] **Step 1: Write failing Stage 1 CLI tests**

Create `tests/contract/test_cli_stage_workflows.py`:

```python
from pathlib import Path

from coding_agent.cli import main


def _stage1_args(tmp_path: Path) -> list[str]:
    return [
        "stage1",
        "run-qwen-vllm",
        "--dataset",
        str(tmp_path / "dev.parquet"),
        "--dataset",
        str(tmp_path / "test.parquet"),
        "--output-dir",
        str(tmp_path / "stage1"),
        "--max-steps",
        "50",
        "--timeout-seconds",
        "900",
        "--test-timeout-seconds",
        "180",
        "--jobs",
        "1",
        "--resume",
    ]


def test_stage1_help_lists_qwen_vllm_command(capsys):
    exit_code = main(["stage1", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "run-qwen-vllm" in captured.out


def test_stage1_run_qwen_vllm_uses_stage1_config_and_official_batch(tmp_path, monkeypatch):
    captured_config = {}
    captured_batch = {}

    def fake_load_stage_model_config(stage, model_override=None):
        captured_config["stage"] = stage
        captured_config["model_override"] = model_override

        class Config:
            model = "qwen2.5-coder-7b"

        return Config()

    def fake_run_official_swebench_batch(**kwargs):
        captured_batch.update(kwargs)
        return 0

    monkeypatch.setattr("coding_agent.cli.load_stage_model_config", fake_load_stage_model_config)
    monkeypatch.setattr("coding_agent.cli.run_official_swebench_batch", fake_run_official_swebench_batch)

    exit_code = main([*_stage1_args(tmp_path), "--model", "qwen-override"])

    assert exit_code == 0
    assert captured_config == {"stage": "stage1", "model_override": "qwen-override"}
    assert captured_batch["dataset_paths"] == (str(tmp_path / "dev.parquet"), str(tmp_path / "test.parquet"))
    assert captured_batch["output_dir"] == Path(tmp_path / "stage1")
    assert captured_batch["jobs"] == 1
    assert captured_batch["resume"] is True
    assert captured_batch["model_name"] == "qwen2.5-coder-7b"


def test_stage1_run_qwen_vllm_rejects_registry(tmp_path, capsys):
    exit_code = main([*_stage1_args(tmp_path), "--registry", "legacy.json"])

    assert exit_code == 2
    assert "registry" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
python -m pytest tests/contract/test_cli_stage_workflows.py -q
```

Expected: FAIL because `stage1` is not a known command.

- [ ] **Step 3: Implement Stage 1 parser and handler**

In `src/coding_agent/cli.py`, update imports:

```python
from coding_agent.model_backends.openai_compatible import (
    MissingModelConfigError,
    OpenAICompatibleBackend,
    load_model_config,
    load_stage_model_config,
)
```

In `build_parser()`, after the `swebench` parser block or before it, add:

```python
    stage1_parser = subparsers.add_parser("stage1", help="Stage 1 local-vLLM SWE-Bench Lite workflows")
    stage1_subparsers = stage1_parser.add_subparsers(dest="stage1_command")
    stage1_run_parser = stage1_subparsers.add_parser(
        "run-qwen-vllm",
        help="evaluate Qwen2.5-Coder-7B-Instruct on SWE-Bench Lite through local vLLM",
    )
    stage1_run_parser.add_argument("--dataset", action="append", required=True, dest="datasets")
    stage1_run_parser.add_argument("--output-dir", required=True)
    stage1_run_parser.add_argument("--max-steps", type=int, required=True)
    stage1_run_parser.add_argument("--timeout-seconds", type=int, required=True)
    stage1_run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    stage1_run_parser.add_argument("--jobs", type=int, default=1)
    stage1_run_parser.add_argument("--build-missing", action="store_true")
    stage1_run_parser.add_argument("--replace-existing", action="store_true")
    stage1_run_parser.add_argument("--resume", action="store_true")
    stage1_run_parser.add_argument("--include-pass-to-pass", action="store_true")
    stage1_run_parser.add_argument("--cleanup", action=argparse.BooleanOptionalAction, default=True)
    stage1_run_parser.add_argument("--arch", choices=("x86_64", "arm64"), default="x86_64")
    stage1_run_parser.add_argument("--model")
    stage1_run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
```

Add this handler near `_swebench_batch_run_command()`:

```python
def _stage1_run_qwen_vllm_command(args: argparse.Namespace) -> int:
    """Run Stage 1 Qwen2.5 local-vLLM SWE-Bench Lite evaluation."""
    logger.info("stage1 run-qwen-vllm started: datasets=%s output_dir=%s jobs=%s", args.datasets, args.output_dir, args.jobs)
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        if args.jobs <= 0:
            raise ValueError("jobs must be a positive integer")
        if args.backend == "mock":
            model_name = args.model or "mock-model"

            def backend_factory():
                return MockBackend()

        else:
            config = load_stage_model_config("stage1", model_override=args.model)
            model_name = config.model

            def backend_factory():
                return OpenAICompatibleBackend(config)

        return run_official_swebench_batch(
            dataset_paths=tuple(args.datasets),
            docker=DockerCli(),
            backend_factory=backend_factory,
            budget=budget,
            model_name=model_name,
            output_dir=Path(args.output_dir),
            jobs=args.jobs,
            build_missing=args.build_missing,
            replace_existing=args.replace_existing,
            resume=args.resume,
            include_pass_to_pass=args.include_pass_to_pass,
            cleanup=args.cleanup,
            active_index_path=Path(".coding-agent/active-sandboxes.json"),
            arch=args.arch,
        )
    except (ValueError, SwebenchDatasetError, SandboxedRunInputError, MissingModelConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ArtifactPersistenceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except SandboxedRunRuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4
```

In `main()`, add before `if args.command == "swebench"`:

```python
    if args.command == "stage1":
        if getattr(args, "stage1_command", None) == "run-qwen-vllm":
            return _stage1_run_qwen_vllm_command(args)
        parser.error("stage1 subcommand is required")
        return 2
```

- [ ] **Step 4: Run Stage 1 tests**

Run:

```bash
python -m pytest tests/contract/test_cli_stage_workflows.py -q
```

Expected: PASS for Stage 1 tests.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/cli.py tests/contract/test_cli_stage_workflows.py
git commit -m "feat: add stage1 qwen vllm workflow"
```

---

### Task 3: Add Stage 2 CLI Workflow

**Files:**
- Modify: `src/coding_agent/cli.py`
- Modify: `tests/contract/test_cli_stage_workflows.py`

- [ ] **Step 1: Add failing Stage 2 tests**

Append to `tests/contract/test_cli_stage_workflows.py`:

```python
def test_stage2_help_lists_teacher_trajectory_command(capsys):
    exit_code = main(["stage2", "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "generate-teacher-trajectories" in captured.out


def test_stage2_generate_teacher_trajectories_uses_stage2_config_and_pipeline(tmp_path, monkeypatch):
    subset = tmp_path / "subset.json"
    subset.write_text("[]", encoding="utf-8")
    captured_config = {}
    captured_run = {}
    captured_eval = {}
    captured_export = {}

    def fake_load_stage_model_config(stage, model_override=None):
        captured_config["stage"] = stage
        captured_config["model_override"] = model_override

        class Config:
            model = "teacher-model"

        return Config()

    def fake_run_swesmith_subset(**kwargs):
        captured_run.update(kwargs)
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "preds.jsonl").write_text("", encoding="utf-8")
        return 0

    def fake_run_official_eval(**kwargs):
        captured_eval.update(kwargs)
        return 0

    def fake_export_sft(**kwargs):
        captured_export.update(kwargs)
        return 12

    monkeypatch.setattr("coding_agent.cli.load_stage_model_config", fake_load_stage_model_config)
    monkeypatch.setattr("coding_agent.cli.run_swesmith_subset", fake_run_swesmith_subset)
    monkeypatch.setattr("coding_agent.cli.run_official_eval", fake_run_official_eval)
    monkeypatch.setattr("coding_agent.cli.export_sft", fake_export_sft)

    exit_code = main(
        [
            "stage2",
            "generate-teacher-trajectories",
            "--subset",
            str(subset),
            "--output-dir",
            str(tmp_path / "runs"),
            "--reference-path",
            str(tmp_path / "Reference" / "SWE-smith"),
            "--max-steps",
            "80",
            "--timeout-seconds",
            "1200",
            "--test-timeout-seconds",
            "180",
            "--jobs",
            "4",
            "--eval-workers",
            "3",
            "--run-id",
            "stage2_teacher",
            "--sft-output",
            str(tmp_path / "sft.jsonl"),
            "--model",
            "teacher-override",
        ]
    )

    assert exit_code == 0
    assert captured_config == {"stage": "stage2", "model_override": "teacher-override"}
    assert captured_run["subset_path"] == str(subset)
    assert captured_run["model_name"] == "teacher-model"
    assert captured_run["jobs"] == 4
    assert captured_eval["dataset_path"] == str(subset)
    assert captured_eval["run_id"] == "stage2_teacher"
    assert captured_eval["workers"] == 3
    assert captured_export["runs_dir"] == str(tmp_path / "runs")
    assert captured_export["output"] == str(tmp_path / "sft.jsonl")


def test_stage2_generate_teacher_trajectories_requires_subset_or_create_args(tmp_path, capsys):
    exit_code = main(
        [
            "stage2",
            "generate-teacher-trajectories",
            "--output-dir",
            str(tmp_path / "runs"),
            "--max-steps",
            "1",
            "--timeout-seconds",
            "60",
            "--test-timeout-seconds",
            "10",
            "--run-id",
            "stage2_teacher",
            "--sft-output",
            str(tmp_path / "sft.jsonl"),
        ]
    )

    assert exit_code == 2
    assert "subset" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
python -m pytest tests/contract/test_cli_stage_workflows.py -q
```

Expected: FAIL because `stage2` is not implemented.

- [ ] **Step 3: Implement Stage 2 parser and handler**

In `build_parser()`, add:

```python
    stage2_parser = subparsers.add_parser("stage2", help="Stage 2 teacher SWE-smith trajectory workflows")
    stage2_subparsers = stage2_parser.add_subparsers(dest="stage2_command")
    stage2_generate_parser = stage2_subparsers.add_parser(
        "generate-teacher-trajectories",
        help="generate teacher API SWE-smith trajectories and export resolved SFT data",
    )
    stage2_generate_parser.add_argument("--subset")
    stage2_generate_parser.add_argument("--create-subset", action="store_true")
    stage2_generate_parser.add_argument("--split", default="train")
    stage2_generate_parser.add_argument("--min-fail-to-pass", type=int, default=2)
    stage2_generate_parser.add_argument("--max-fail-to-pass", type=int, default=5)
    stage2_generate_parser.add_argument("--require-pr", action="store_true")
    stage2_generate_parser.add_argument("--languages", help="comma-separated language filter, e.g. python,cpp")
    stage2_generate_parser.add_argument("--output-dir", required=True)
    stage2_generate_parser.add_argument("--reference-path")
    stage2_generate_parser.add_argument("--max-steps", type=int, required=True)
    stage2_generate_parser.add_argument("--timeout-seconds", type=int, required=True)
    stage2_generate_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    stage2_generate_parser.add_argument("--jobs", type=int, default=1)
    stage2_generate_parser.add_argument("--eval-workers", type=int, default=4)
    stage2_generate_parser.add_argument("--run-id", required=True)
    stage2_generate_parser.add_argument("--sft-output", required=True)
    stage2_generate_parser.add_argument("--cleanup-images", action="store_true")
    stage2_generate_parser.add_argument("--model")
    stage2_generate_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
```

Add handler:

```python
def _stage2_generate_teacher_trajectories_command(args: argparse.Namespace) -> int:
    """Run Stage 2 teacher SWE-smith trajectory generation pipeline."""
    try:
        output_dir = Path(args.output_dir)
        subset_path = Path(args.subset) if args.subset else output_dir / "subset.json"
        if args.subset is None and not args.create_subset:
            raise ValueError("--subset is required unless --create-subset is supplied")
        if args.create_subset:
            languages_list = (
                [lang.strip() for lang in (args.languages or "").split(",") if lang.strip()]
                if args.languages
                else None
            )
            instances = load_huggingface_swesmith(split=args.split)
            create_subset_file(
                subset_path,
                instances=instances,
                require_pr=args.require_pr,
                min_fail_to_pass=args.min_fail_to_pass,
                max_fail_to_pass=args.max_fail_to_pass,
                languages=languages_list,
                reference_path=args.reference_path,
            )

        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        if args.backend == "mock":
            model_name = args.model or "mock-model"

            def backend_factory():
                return MockBackend()

        else:
            config = load_stage_model_config("stage2", model_override=args.model)
            model_name = config.model

            def backend_factory():
                return OpenAICompatibleBackend(config)

        run_exit = run_swesmith_subset(
            subset_path=str(subset_path),
            docker=DockerCli(),
            backend_factory=backend_factory,
            budget=budget,
            model_name=model_name,
            output_dir=output_dir,
            reference_path=args.reference_path,
            jobs=args.jobs,
            cleanup_images=args.cleanup_images,
        )
        predictions_path = output_dir / "preds.jsonl"
        eval_exit = run_official_eval(
            dataset_path=str(subset_path),
            predictions_path=str(predictions_path),
            run_id=args.run_id,
            workers=args.eval_workers,
            reference_path=args.reference_path,
        )
        eval_dir = Path("logs/run_evaluation") / args.run_id
        count = export_sft(runs_dir=str(output_dir), eval_dir=str(eval_dir), output=args.sft_output, style="xml")
        print(json.dumps({"output": args.sft_output, "count": count}, indent=2))
        if eval_exit != 0:
            return eval_exit
        return run_exit
    except (ValueError, SwesmithDatasetError, SwesmithRuntimeError, MissingModelConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ArtifactPersistenceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4
```

In `main()`, add before `if args.command == "swebench"`:

```python
    if args.command == "stage2":
        if getattr(args, "stage2_command", None) == "generate-teacher-trajectories":
            return _stage2_generate_teacher_trajectories_command(args)
        parser.error("stage2 subcommand is required")
        return 2
```

- [ ] **Step 4: Run Stage 2 tests**

Run:

```bash
python -m pytest tests/contract/test_cli_stage_workflows.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/cli.py tests/contract/test_cli_stage_workflows.py
git commit -m "feat: add stage2 teacher trajectory workflow"
```

---

### Task 4: Remove CLI Legacy Positive SWE-Bench Dispatch

**Files:**
- Modify: `src/coding_agent/cli.py`
- Modify: `tests/contract/test_cli_swebench_runtime_contract.py`

- [ ] **Step 1: Add failing test that legacy helpers are not imported by CLI**

Append to `tests/contract/test_cli_swebench_runtime_contract.py`:

```python
def test_cli_does_not_import_legacy_positive_swebench_runtime_helpers():
    import coding_agent.cli as cli

    for name in (
        "prepare_swebench_sandbox",
        "solve_prepared_sandbox",
        "run_swebench_task",
        "prepare_swebench_sandboxes",
        "solve_swebench_sandboxes",
        "run_swebench_tasks",
        "load_base_image_from_registry",
    ):
        assert not hasattr(cli, name)
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
python -m pytest tests/contract/test_cli_swebench_runtime_contract.py::test_cli_does_not_import_legacy_positive_swebench_runtime_helpers -q
```

Expected: FAIL because `cli` currently imports some legacy helper names.

- [ ] **Step 3: Remove legacy imports and dead handlers from CLI**

In `src/coding_agent/cli.py`, remove these imports from `coding_agent.swebench.sandbox_run`:

```python
    load_active_sandbox,
    load_base_image_from_registry,
    parse_instance_id_file,
    prepare_swebench_sandboxes,
    prepare_swebench_sandbox,
    run_swebench_task,
    run_swebench_tasks,
    solve_swebench_sandboxes,
    solve_prepared_sandbox,
```

Delete these functions entirely:

```python
_legacy_swebench_run_command
_swebench_prepare_sandbox_command
_swebench_solve_sandbox_command
_swebench_prepare_sandboxes_command
_swebench_solve_sandboxes_command
```

Keep `LEGACY_SWEBENCH_OPERATIONS` and `_reject_legacy_swebench_operation()` so old commands still return unsupported-operation errors.

- [ ] **Step 4: Run CLI contract tests**

Run:

```bash
python -m pytest tests/contract/test_cli_swebench_runtime_contract.py tests/contract/test_cli_stage_workflows.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/cli.py tests/contract/test_cli_swebench_runtime_contract.py
git commit -m "refactor: remove legacy swebench cli dispatch"
```

---

### Task 5: Remove Legacy SWE-Bench Positive Runtime Helpers and Tests

**Files:**
- Modify: `src/coding_agent/swebench/sandbox_run.py`
- Delete: `tests/integration/test_swebench_sandbox_run.py`
- Delete: `tests/integration/test_swebench_batch_run.py`
- Delete: `tests/integration/test_sandbox_reuse.py`
- Delete: `tests/integration/test_swebench_validation_integration.py`
- Modify tests if any remaining imports fail.

- [ ] **Step 1: Locate all legacy helper consumers**

Run:

```bash
rg -n "prepare_swebench_sandbox|solve_prepared_sandbox|run_swebench_task|prepare_swebench_sandboxes|solve_swebench_sandboxes|run_swebench_tasks|load_base_image_from_registry" src tests
```

Expected: Output shows legacy helper definitions in `sandbox_run.py` and positive legacy tests. Official runtime tests should use `prepare_official_swebench_runtime`, `run_prepared_swebench_runtime`, or `run_official_swebench_batch`.

- [ ] **Step 2: Delete positive legacy integration tests**

Remove these files if their only purpose is legacy positive runtime coverage:

```bash
git rm tests/integration/test_swebench_sandbox_run.py
git rm tests/integration/test_swebench_batch_run.py
git rm tests/integration/test_sandbox_reuse.py
git rm tests/integration/test_swebench_validation_integration.py
```

- [ ] **Step 3: Remove legacy helper code from `sandbox_run.py`**

In `src/coding_agent/swebench/sandbox_run.py`, delete:

```python
validation_from_task
_sandbox_payload
_write_sandbox_json
prepare_swebench_sandbox
solve_prepared_sandbox
prepare_swebench_sandboxes
solve_swebench_sandboxes
_load_base_images_for_records
run_swebench_tasks
run_swebench_task
load_base_image_from_registry
```

Also remove imports only needed by those functions:

```python
BaseImage
BenchmarkTask
PreparedSandboxSummary
SandboxMetadata
TaskSandbox
registry_load_base_image
build_validation_test_set
```

Do not delete helper functions used by official runtime:

```python
prepare_official_swebench_runtime
run_prepared_swebench_runtime
run_official_swebench_batch
parse_instance_id_file
_safe_instance_dir
_prediction_from_run_dir
```

- [ ] **Step 4: Run search to verify legacy positive symbols are gone**

Run:

```bash
rg -n "def prepare_swebench_sandbox|def solve_prepared_sandbox|def run_swebench_task|def prepare_swebench_sandboxes|def solve_swebench_sandboxes|def run_swebench_tasks|legacy_registry|registered_template" src tests
```

Expected: No definitions of removed helpers. `registered_template` may remain only in lower-level validation tests if explicitly scoped as legacy; remove those tests if they assert new runtime fallback.

- [ ] **Step 5: Run focused official-runtime tests**

Run:

```bash
python -m pytest tests/contract/test_cli_swebench_runtime_contract.py tests/contract/test_cli_swebench_run_contract.py tests/integration/test_swebench_official_runtime.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/coding_agent/swebench/sandbox_run.py tests/contract/test_cli_swebench_runtime_contract.py tests/contract/test_cli_swebench_run_contract.py
git add -u tests/integration
git commit -m "refactor: remove legacy swebench runtime helpers"
```

---

### Task 6: Add Stage Scripts and Deploy Bootstrap

**Files:**
- Modify: `scripts/deploy.sh`
- Create: `scripts/run_stage1_qwen_vllm.sh`
- Create: `scripts/run_stage2_teacher_trajectories.sh`
- Modify: `scripts/run_sft_pipeline.sh`
- Test: `tests/contract/test_stage_scripts.py`

- [ ] **Step 1: Write script contract tests**

Create `tests/contract/test_stage_scripts.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_deploy_script_creates_stage_env_templates():
    text = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    assert ".env.stage1.example" in text
    assert ".env.stage2.example" in text
    assert "STAGE1_BASE_URL" in text
    assert "STAGE2_BASE_URL" in text
    assert "run_stage1_qwen_vllm.sh" in text
    assert "run_stage2_teacher_trajectories.sh" in text


def test_stage1_script_uses_stage1_env_and_stage1_cli():
    text = (ROOT / "scripts" / "run_stage1_qwen_vllm.sh").read_text(encoding="utf-8")

    assert "STAGE1_PROVIDER" in text
    assert "STAGE1_MODEL" in text
    assert "STAGE1_API_KEY" in text
    assert "STAGE1_BASE_URL" in text
    assert "coding-agent stage1 run-qwen-vllm" in text
    assert "STAGE2_" not in text


def test_stage2_script_uses_stage2_env_and_stage2_cli():
    text = (ROOT / "scripts" / "run_stage2_teacher_trajectories.sh").read_text(encoding="utf-8")

    assert "STAGE2_PROVIDER" in text
    assert "STAGE2_MODEL" in text
    assert "STAGE2_API_KEY" in text
    assert "STAGE2_BASE_URL" in text
    assert "coding-agent stage2 generate-teacher-trajectories" in text
    assert "STAGE1_" not in text


def test_old_sft_pipeline_is_compatibility_wrapper():
    text = (ROOT / "scripts" / "run_sft_pipeline.sh").read_text(encoding="utf-8")

    assert "deprecated" in text.lower()
    assert "run_stage2_teacher_trajectories.sh" in text
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
python -m pytest tests/contract/test_stage_scripts.py -q
```

Expected: FAIL because new scripts and deploy markers do not exist yet.

- [ ] **Step 3: Create Stage 1 script**

Create `scripts/run_stage1_qwen_vllm.sh`:

```bash
#!/bin/bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
DATASETS="${DATASETS:-$PROJECT_DIR/data/dev-00000-of-00001.parquet $PROJECT_DIR/data/test-00000-of-00001.parquet}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/runs/stage1_qwen25_lite}"
MAX_STEPS="${MAX_STEPS:-50}"
TIMEOUT_SEC="${TIMEOUT_SEC:-900}"
TEST_TIMEOUT_SEC="${TEST_TIMEOUT_SEC:-180}"
JOBS="${JOBS:-1}"

for key in STAGE1_PROVIDER STAGE1_MODEL STAGE1_API_KEY STAGE1_BASE_URL; do
    if [[ -z "${!key:-}" ]]; then
        echo "missing $key" >&2
        exit 2
    fi
done

if [[ -f "$VENV_DIR/bin/activate" ]]; then
    source "$VENV_DIR/bin/activate"
fi

args=(coding-agent stage1 run-qwen-vllm)
for dataset in $DATASETS; do
    args+=(--dataset "$dataset")
done
args+=(
    --output-dir "$OUTPUT_DIR"
    --max-steps "$MAX_STEPS"
    --timeout-seconds "$TIMEOUT_SEC"
    --test-timeout-seconds "$TEST_TIMEOUT_SEC"
    --jobs "$JOBS"
    --resume
)

echo "Stage 1 model: $STAGE1_MODEL"
echo "Stage 1 endpoint: $STAGE1_BASE_URL"
exec "${args[@]}"
```

- [ ] **Step 4: Create Stage 2 script**

Create `scripts/run_stage2_teacher_trajectories.sh`:

```bash
#!/bin/bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
SWE_SMITH_REF="${SWE_SMITH_REF:-$PROJECT_DIR/Reference/SWE-smith}"
RUN_ID="${RUN_ID:-stage2_teacher_$(date +%Y%m%d_%H%M%S)}"
SUBSET_FILE="${SUBSET_FILE:-$PROJECT_DIR/data/subset.json}"
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_DIR/runs/$RUN_ID}"
SFT_OUTPUT="${SFT_OUTPUT:-$PROJECT_DIR/sft_data/$RUN_ID.jsonl}"
MAX_STEPS="${MAX_STEPS:-80}"
TIMEOUT_SEC="${TIMEOUT_SEC:-1200}"
TEST_TIMEOUT_SEC="${TEST_TIMEOUT_SEC:-180}"
JOBS="${JOBS:-4}"
EVAL_WORKERS="${EVAL_WORKERS:-4}"

for key in STAGE2_PROVIDER STAGE2_MODEL STAGE2_API_KEY STAGE2_BASE_URL; do
    if [[ -z "${!key:-}" ]]; then
        echo "missing $key" >&2
        exit 2
    fi
done

if [[ -f "$VENV_DIR/bin/activate" ]]; then
    source "$VENV_DIR/bin/activate"
fi

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/runs" "$PROJECT_DIR/sft_data"

args=(
    coding-agent stage2 generate-teacher-trajectories
    --subset "$SUBSET_FILE"
    --output-dir "$OUTPUT_DIR"
    --reference-path "$SWE_SMITH_REF"
    --max-steps "$MAX_STEPS"
    --timeout-seconds "$TIMEOUT_SEC"
    --test-timeout-seconds "$TEST_TIMEOUT_SEC"
    --jobs "$JOBS"
    --eval-workers "$EVAL_WORKERS"
    --run-id "$RUN_ID"
    --sft-output "$SFT_OUTPUT"
)

if [[ ! -f "$SUBSET_FILE" ]]; then
    args+=(--create-subset)
fi

echo "Stage 2 model: $STAGE2_MODEL"
echo "Stage 2 endpoint: $STAGE2_BASE_URL"
exec "${args[@]}"
```

- [ ] **Step 5: Update deploy script**

In `scripts/deploy.sh`:

- Change title to `Stage 1/2 Workflow Deployment`.
- Create directories:

```bash
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/runs" "$PROJECT_DIR/sft_data" "$PROJECT_DIR/logs"
```

- Replace `.env` template creation with `.env.stage1.example` and `.env.stage2.example`:

```bash
cat > "$PROJECT_DIR/.env.stage1.example" <<'ENVEOF'
STAGE1_PROVIDER=openai
STAGE1_MODEL=qwen2.5-coder-7b
STAGE1_API_KEY=not-needed
STAGE1_BASE_URL=http://vllm-stage1.internal:8000/v1
ENVEOF

cat > "$PROJECT_DIR/.env.stage2.example" <<'ENVEOF'
STAGE2_PROVIDER=openai
STAGE2_MODEL=teacher-model-name
STAGE2_API_KEY=teacher-api-key
STAGE2_BASE_URL=https://teacher.example/v1
ENVEOF
```

- Update next steps:

```bash
echo "    3. cp .env.stage1.example .env.stage1 && edit it"
echo "    4. cp .env.stage2.example .env.stage2 && edit it"
echo "    5. source .env.stage1 && ./scripts/run_stage1_qwen_vllm.sh"
echo "    6. source .env.stage2 && ./scripts/run_stage2_teacher_trajectories.sh"
```

- Do not run vLLM and do not store real API keys.

- [ ] **Step 6: Convert old SFT script to wrapper**

Replace `scripts/run_sft_pipeline.sh` with:

```bash
#!/bin/bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

echo "WARNING: scripts/run_sft_pipeline.sh is deprecated." >&2
echo "Use scripts/run_stage2_teacher_trajectories.sh for Stage 2 teacher trajectory generation." >&2

exec "$PROJECT_DIR/scripts/run_stage2_teacher_trajectories.sh" "$@"
```

- [ ] **Step 7: Run script tests**

Run:

```bash
python -m pytest tests/contract/test_stage_scripts.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/deploy.sh scripts/run_stage1_qwen_vllm.sh scripts/run_stage2_teacher_trajectories.sh scripts/run_sft_pipeline.sh tests/contract/test_stage_scripts.py
git commit -m "feat: add stage workflow scripts"
```

---

### Task 7: Update Documentation to Canonical Stage Flow

**Files:**
- Modify: `README.md`
- Modify: `docs/cost_optimized_two_stage_deployment.md`
- Modify: `docs/swesmith_sft_pipeline_guide.md`
- Do not modify: `docs/training_stage3_stage4_roadmap_zh.md`

- [ ] **Step 1: Add documentation tests**

Create `tests/contract/test_stage_docs.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_readme_points_to_stage_entrypoints():
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "coding-agent stage1 run-qwen-vllm" in text
    assert "coding-agent stage2 generate-teacher-trajectories" in text
    assert "STAGE1_BASE_URL" in text
    assert "STAGE2_BASE_URL" in text


def test_cost_doc_uses_stage_scripts():
    text = (ROOT / "docs" / "cost_optimized_two_stage_deployment.md").read_text(encoding="utf-8")

    assert "scripts/run_stage1_qwen_vllm.sh" in text
    assert "scripts/run_stage2_teacher_trajectories.sh" in text
    assert "STAGE1_MODEL" in text
    assert "STAGE2_MODEL" in text


def test_swesmith_guide_marks_local_vllm_as_lower_level_not_stage2_default():
    text = (ROOT / "docs" / "swesmith_sft_pipeline_guide.md").read_text(encoding="utf-8")

    assert "run_stage2_teacher_trajectories.sh" in text
    assert "lower-level" in text.lower()
    assert "Stage 2" in text
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
python -m pytest tests/contract/test_stage_docs.py -q
```

Expected: FAIL because docs still point to old generic commands/scripts.

- [ ] **Step 3: Update README**

In `README.md`, add a section near the quickstart:

```markdown
## Canonical Stage Workflows

Stage 1 baseline:

```bash
source .env.stage1
coding-agent stage1 run-qwen-vllm \
  --dataset data/dev-00000-of-00001.parquet \
  --dataset data/test-00000-of-00001.parquet \
  --output-dir runs/stage1_qwen25_lite \
  --max-steps 50 \
  --timeout-seconds 900 \
  --test-timeout-seconds 180 \
  --jobs 1 \
  --resume
```

Stage 2 teacher trajectory generation:

```bash
source .env.stage2
coding-agent stage2 generate-teacher-trajectories \
  --subset data/subset.json \
  --output-dir runs/stage2_teacher \
  --reference-path Reference/SWE-smith \
  --max-steps 80 \
  --timeout-seconds 1200 \
  --test-timeout-seconds 180 \
  --jobs 4 \
  --eval-workers 4 \
  --run-id stage2_teacher \
  --sft-output sft_data/stage2_teacher.jsonl
```

Stage 1 reads `STAGE1_PROVIDER`, `STAGE1_MODEL`, `STAGE1_API_KEY`, and
`STAGE1_BASE_URL`. Stage 2 reads `STAGE2_PROVIDER`, `STAGE2_MODEL`,
`STAGE2_API_KEY`, and `STAGE2_BASE_URL`.
```

- [ ] **Step 4: Update cost deployment doc**

In `docs/cost_optimized_two_stage_deployment.md`:

- Replace direct Stage 1 `coding-agent swebench batch-run` examples with:

```bash
source .env.stage1
./scripts/run_stage1_qwen_vllm.sh
```

- Replace Stage 2 `./scripts/run_sft_pipeline.sh` examples with:

```bash
source .env.stage2
./scripts/run_stage2_teacher_trajectories.sh
```

- Replace generic `MODEL/API_KEY/BASE_URL` examples with `STAGE1_*` and `STAGE2_*`.

- [ ] **Step 5: Update SWE-smith guide**

In `docs/swesmith_sft_pipeline_guide.md`:

- Add this note near local vLLM usage:

```markdown
Local vLLM remains a lower-level SWE-smith capability, but it is not the
recommended Stage 2 path. Stage 2 teacher trajectory generation should use
`STAGE2_*` teacher API configuration and `scripts/run_stage2_teacher_trajectories.sh`.
```

- Replace primary pipeline references to `run_sft_pipeline.sh` with `run_stage2_teacher_trajectories.sh`.

- [ ] **Step 6: Run doc tests**

Run:

```bash
python -m pytest tests/contract/test_stage_docs.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/cost_optimized_two_stage_deployment.md docs/swesmith_sft_pipeline_guide.md tests/contract/test_stage_docs.py
git commit -m "docs: document canonical stage workflows"
```

---

### Task 8: Full Focused Verification and Cleanup

**Files:**
- Any files changed by prior tasks.

- [ ] **Step 1: Run focused verification suite**

Run:

```bash
python -m pytest \
  tests/contract/test_cli_swebench_runtime_contract.py \
  tests/contract/test_cli_swebench_run_contract.py \
  tests/contract/test_cli_swesmith_contract.py \
  tests/contract/test_cli_stage_workflows.py \
  tests/contract/test_stage_scripts.py \
  tests/contract/test_stage_docs.py \
  tests/unit/test_openai_compatible_config.py \
  tests/unit/test_swesmith_run.py \
  tests/unit/test_swesmith_export_sft.py \
  tests/integration/test_swebench_official_runtime.py \
  tests/integration/test_swesmith_pipeline_fake.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Search for removed legacy symbols**

Run:

```bash
rg -n "prepare_swebench_sandbox|solve_prepared_sandbox|run_swebench_task|prepare_swebench_sandboxes|solve_swebench_sandboxes|run_swebench_tasks|legacy_registry|registered_template" src tests README.md docs scripts
```

Expected:

- No legacy positive helper definitions or imports.
- `registered_template` appears only if explicitly documented as removed legacy behavior; otherwise remove remaining references.
- `legacy_registry` does not appear in new Stage 1/2 paths.

- [ ] **Step 3: Check git status and avoid unrelated user changes**

Run:

```bash
git status --short
```

Expected:

- Only files from this implementation are modified.
- If `docs/training_stage3_stage4_roadmap_zh.md` is still modified from before, leave it unstaged unless the user explicitly asks to include it.

- [ ] **Step 4: Run formatting/check command**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Commit final cleanup if needed**

If Step 1-4 required any fixes:

```bash
git add src tests scripts README.md docs/cost_optimized_two_stage_deployment.md docs/swesmith_sft_pipeline_guide.md
git commit -m "test: verify stage workflow boundary"
```

If no fixes were required, no commit is needed.

---

## Self-Review

- Spec coverage: Stage CLI, stage env isolation, scripts, `deploy.sh`, legacy positive runtime cleanup, docs, and fake-backed tests are covered by Tasks 1-8.
- Placeholder scan: No unresolved marker or unspecified implementation step is intentional. Every code-changing task includes concrete target files and commands.
- Type consistency: `load_stage_model_config(stage, env=None, dotenv_path=".env", model_override=None)` returns `ModelConfig`, matching `OpenAICompatibleBackend(config)` use in CLI handlers. Stage command names match the design: `stage1 run-qwen-vllm` and `stage2 generate-teacher-trajectories`.
