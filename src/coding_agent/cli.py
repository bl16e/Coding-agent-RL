from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from coding_agent.agent import ArtifactPersistenceError, ToolAgent, AgentConfig
from coding_agent.model_backend import ModelBackend
from coding_agent.models import BenchmarkTask, RunBudget, RunStatus, UnsupportedLegacyOperation, UnsupportedLegacySurface
from coding_agent.mock_backend import MockBackend
from coding_agent.openai_compatible_backend import (
    MissingModelConfigError,
    OpenAICompatibleBackend,
    load_model_config,
    parse_dotenv,
    load_stage_model_config,
)
from coding_agent.sandbox_manager import DockerCli, SandboxManager
from coding_agent.sandbox_registry import SandboxRegistry, SandboxRegistryError, register_base_image
from coding_agent.tools.executor import SweRexToolExecutor
from coding_agent.trajectory_exporter import TrajectoryExporter
from coding_agent.swebench.dataset import SwebenchDatasetError
from coding_agent.swebench.prediction import export_prediction_from_run
from coding_agent.swebench.evaluate import (
    compute_aggregate_metrics,
    load_evaluation_results,
    render_evaluation_report,
)
from coding_agent.swebench.sandbox_run import (
    SandboxedRunInputError,
    SandboxedRunRuntimeError,
    prepare_official_swebench_runtime,
    run_official_swebench_batch,
    run_prepared_swebench_runtime,
)
from coding_agent.swesmith.dataset import SwesmithDatasetError, create_subset_file, load_huggingface_swesmith
from coding_agent.swesmith.evaluate import run_official_eval
from coding_agent.swesmith.export_sft import export_sft
from coding_agent.swesmith.quality_gate import run_quality_gate
from coding_agent.swesmith.run import run_swesmith_subset
from coding_agent.swesmith.runtime import SwesmithRuntimeError
from coding_agent.swesmith.training_manifest import (
    SwesmithTrainingManifestError,
    create_training_manifest_from_input,
    update_training_manifest,
)
from coding_agent.trajectory_exporter import load_summary, load_trajectory, render_inspect_report


logger = logging.getLogger(__name__)


LEGACY_SWEBENCH_OPERATIONS = {
    "prepare-sandbox": UnsupportedLegacyOperation(
        operation_name="prepare-sandbox",
        legacy_surface=UnsupportedLegacySurface.SANDBOX_COMMAND,
        replacement="prepare",
        error_message=(
            "unsupported SWE-Bench runtime operation 'prepare-sandbox'; "
            "use 'coding-agent swebench prepare' to prepare environments and "
            "'coding-agent swebench run' to run the agent"
        ),
    ),
    "solve-sandbox": UnsupportedLegacyOperation(
        operation_name="solve-sandbox",
        legacy_surface=UnsupportedLegacySurface.SANDBOX_COMMAND,
        replacement="run",
        error_message=(
            "unsupported SWE-Bench runtime operation 'solve-sandbox'; "
            "use 'coding-agent swebench prepare' to prepare environments and "
            "'coding-agent swebench run' to run the agent"
        ),
    ),
    "prepare-sandboxes": UnsupportedLegacyOperation(
        operation_name="prepare-sandboxes",
        legacy_surface=UnsupportedLegacySurface.BATCH_COMMAND,
        replacement="prepare",
        error_message=(
            "unsupported batch SWE-Bench runtime operation 'prepare-sandboxes'; "
            "use 'coding-agent swebench prepare' to prepare one task environment and "
            "'coding-agent swebench run' to run the agent"
        ),
    ),
    "solve-sandboxes": UnsupportedLegacyOperation(
        operation_name="solve-sandboxes",
        legacy_surface=UnsupportedLegacySurface.BATCH_COMMAND,
        replacement="run",
        error_message=(
            "unsupported batch SWE-Bench runtime operation 'solve-sandboxes'; "
            "use 'coding-agent swebench prepare' to prepare one task environment and "
            "'coding-agent swebench run' to run the agent"
        ),
    ),
}


def build_parser() -> argparse.ArgumentParser:
    """构造完整 CLI。

    这个项目刻意把 argparse 留在最外层：子命令只收集字符串/数字参数，真正的领域
    校验会下沉到 models、registry、dataset 和 sandbox_run，便于测试库函数。
    """
    parser = argparse.ArgumentParser(prog="coding-agent")
    parser.add_argument("--verbose", action="store_true", help="show debug-level progress logs")
    parser.add_argument("--log-file", help="write progress logs to this file")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="run one prepared SWE-Bench Lite task")
    run_parser.add_argument("--instance-id", required=True)
    run_parser.add_argument("--workspace", required=True)
    run_parser.add_argument("--problem-statement-file", required=True)
    run_parser.add_argument("--allowed-test", action="append", required=True, dest="allowed_tests")
    run_parser.add_argument("--max-steps", type=int, required=True)
    run_parser.add_argument("--timeout-seconds", type=int, required=True)
    run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--model")
    run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    inspect_parser = subparsers.add_parser("inspect", help="inspect a completed run directory")
    inspect_parser.add_argument("--run-dir", required=True)
    export_parser = subparsers.add_parser("export-prediction", help="export prediction JSONL")
    export_parser.add_argument("--run-dir", required=True)
    export_parser.add_argument("--model-name", required=True)
    export_parser.add_argument("--output", required=True)
    sandbox_parser = subparsers.add_parser("sandbox", help="Docker sandbox registry commands")
    sandbox_subparsers = sandbox_parser.add_subparsers(dest="sandbox_command")
    sandbox_register_parser = sandbox_subparsers.add_parser("register", help="register a prepared base image")
    sandbox_register_parser.add_argument("--repo", required=True)
    sandbox_register_parser.add_argument("--image", required=True)
    sandbox_register_parser.add_argument("--repo-path", required=True)
    sandbox_register_parser.add_argument("--registry", default=".coding-agent/sandboxes.json")
    sandbox_register_parser.add_argument("--official-compatible", action="store_true")
    sandbox_register_parser.add_argument("--compatibility-source")
    sandbox_register_parser.add_argument("--validation-command-template")
    sandbox_list_parser = sandbox_subparsers.add_parser("list", help="list registered base images")
    sandbox_list_parser.add_argument("--registry", default=".coding-agent/sandboxes.json")
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
    stage2_generate_parser.add_argument("--model", nargs="?")
    stage2_generate_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    swebench_parser = subparsers.add_parser("swebench", help="SWE-Bench commands")
    swebench_subparsers = swebench_parser.add_subparsers(dest="swebench_command")
    swebench_official_prepare_parser = swebench_subparsers.add_parser(
        "prepare",
        help="prepare official-style SWE-Bench runtime layers and task environment",
    )
    swebench_official_prepare_parser.add_argument("--dataset", required=True)
    swebench_official_prepare_parser.add_argument("--instance-id", required=True)
    swebench_official_prepare_parser.add_argument("--output-dir", required=True)
    swebench_official_prepare_parser.add_argument("--build-missing", action="store_true")
    swebench_official_prepare_parser.add_argument("--replace-existing", action="store_true")
    swebench_official_prepare_parser.add_argument("--arch", choices=("x86_64", "arm64"), default="x86_64")
    swebench_run_parser = swebench_subparsers.add_parser("run", help="run a prepared official-style SWE-Bench task")
    swebench_run_parser.add_argument("--dataset", required=True)
    swebench_run_parser.add_argument("--instance-id", required=True)
    swebench_run_parser.add_argument("--max-steps", type=int, required=True)
    swebench_run_parser.add_argument("--timeout-seconds", type=int, required=True)
    swebench_run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    swebench_run_parser.add_argument("--output-dir", required=True)
    swebench_run_parser.add_argument("--include-pass-to-pass", action="store_true")
    swebench_run_parser.add_argument("--cleanup", action="store_true")
    swebench_run_parser.add_argument("--model")
    swebench_run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    swebench_batch_run_parser = swebench_subparsers.add_parser(
        "batch-run",
        help="run all tasks from one or more SWE-Bench Lite datasets",
    )
    swebench_batch_run_parser.add_argument("--dataset", action="append", required=True, dest="datasets")
    swebench_batch_run_parser.add_argument("--max-steps", type=int, required=True)
    swebench_batch_run_parser.add_argument("--timeout-seconds", type=int, required=True)
    swebench_batch_run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    swebench_batch_run_parser.add_argument("--output-dir", required=True)
    swebench_batch_run_parser.add_argument("--jobs", type=int, default=1)
    swebench_batch_run_parser.add_argument("--build-missing", action="store_true")
    swebench_batch_run_parser.add_argument("--replace-existing", action="store_true")
    swebench_batch_run_parser.add_argument("--resume", action="store_true")
    swebench_batch_run_parser.add_argument("--include-pass-to-pass", action="store_true")
    swebench_batch_run_parser.add_argument("--cleanup", action=argparse.BooleanOptionalAction, default=True)
    swebench_batch_run_parser.add_argument("--arch", choices=("x86_64", "arm64"), default="x86_64")
    swebench_batch_run_parser.add_argument("--model")
    swebench_batch_run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    swebench_evaluate_parser = swebench_subparsers.add_parser(
        "evaluate",
        help="evaluate aggregate results from a batch run",
    )
    swebench_evaluate_parser.add_argument("--batch-dir", required=True)
    swebench_evaluate_parser.add_argument("--json", action="store_true", dest="json_output")
    swebench_evaluate_parser.add_argument("--output")
    swesmith_parser = subparsers.add_parser("swesmith", help="SWE-smith training trajectory commands")
    swesmith_subparsers = swesmith_parser.add_subparsers(dest="swesmith_command")
    swesmith_create_parser = swesmith_subparsers.add_parser("create-subset", help="create a local SWE-smith subset file")
    swesmith_create_parser.add_argument("--out", required=True)
    swesmith_create_parser.add_argument("--split", default="train")
    swesmith_create_parser.add_argument("--min-fail-to-pass", type=int, default=2)
    swesmith_create_parser.add_argument("--max-fail-to-pass", type=int, default=5)
    swesmith_create_parser.add_argument("--require-pr", action="store_true")
    swesmith_create_parser.add_argument("--languages", help="comma-separated language filter, e.g. python,cpp")
    swesmith_create_parser.add_argument("--reference-path", help="path to SWE-smith checkout for language filtering")
    swesmith_run_parser = swesmith_subparsers.add_parser("run-subset", help="run current agent on a SWE-smith subset")
    swesmith_run_parser.add_argument("--subset", required=True)
    swesmith_run_parser.add_argument("--output-dir", required=True)
    swesmith_run_parser.add_argument("--max-steps", type=int, required=True)
    swesmith_run_parser.add_argument("--timeout-seconds", type=int, required=True)
    swesmith_run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    swesmith_run_parser.add_argument("--jobs", type=int, default=1)
    swesmith_run_parser.add_argument("--reference-path")
    swesmith_run_parser.add_argument("--cleanup-images", action="store_true", help="remove Docker images after run completes")
    swesmith_run_parser.add_argument("--model")
    swesmith_run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    swesmith_eval_parser = swesmith_subparsers.add_parser("eval", help="run official SWE-smith evaluation")
    swesmith_eval_parser.add_argument("--subset", required=True)
    swesmith_eval_parser.add_argument("--predictions", required=True)
    swesmith_eval_parser.add_argument("--run-id", required=True)
    swesmith_eval_parser.add_argument("--workers", type=int, default=10)
    swesmith_eval_parser.add_argument("--reference-path")
    swesmith_export_parser = swesmith_subparsers.add_parser("export-sft", help="export resolved trajectories to SFT JSONL")
    swesmith_export_parser.add_argument("--runs", required=True)
    swesmith_export_parser.add_argument("--eval-dir", required=True)
    swesmith_export_parser.add_argument("--out", required=True)
    swesmith_export_parser.add_argument("--style", choices=("xml",), default="xml")
    swesmith_quality_parser = swesmith_subparsers.add_parser("quality-gate", help="write SWE-smith trajectory quality report and filtered SFT JSONL")
    swesmith_quality_parser.add_argument("--runs", required=True)
    swesmith_quality_parser.add_argument("--eval-dir", required=True)
    swesmith_quality_parser.add_argument("--out", required=True, help="quality report JSON output")
    swesmith_quality_parser.add_argument("--filtered-sft", required=True, help="filtered SFT JSONL output")
    swesmith_manifest_parser = swesmith_subparsers.add_parser(
        "create-training-manifest",
        help="create SWE-smith SFT/RL training manifest and initial split files",
    )
    swesmith_manifest_parser.add_argument("--input", required=True, help="local SWE-smith .json, .jsonl, .parquet, or parquet directory")
    swesmith_manifest_parser.add_argument("--out", required=True)
    swesmith_manifest_parser.add_argument("--splits-dir", required=True)
    swesmith_manifest_parser.add_argument("--languages", help="comma-separated language filter, e.g. python,cpp")
    swesmith_manifest_parser.add_argument("--reference-path", help="path to SWE-smith checkout for language filtering")
    swesmith_manifest_parser.add_argument("--sft-repos-file", help="newline-delimited repo ids allowed for SFT candidates")
    swesmith_manifest_parser.add_argument("--easy-fail-to-pass-max", type=int, default=1)
    swesmith_manifest_parser.add_argument("--medium-fail-to-pass-min", type=int, default=2)
    swesmith_manifest_parser.add_argument("--medium-fail-to-pass-max", type=int, default=5)
    swesmith_manifest_parser.add_argument("--sft-candidate-limit", type=int, default=3000)
    swesmith_manifest_parser.add_argument("--grpo-dev-count", type=int, default=300)
    swesmith_manifest_parser.add_argument("--heldout-count", type=int, default=500)
    swesmith_manifest_parser.add_argument("--seed", type=int, default=42)
    swesmith_update_manifest_parser = swesmith_subparsers.add_parser(
        "update-training-manifest",
        help="update SWE-smith training manifest from teacher quality outputs",
    )
    swesmith_update_manifest_parser.add_argument("--manifest", required=True)
    swesmith_update_manifest_parser.add_argument("--runs")
    swesmith_update_manifest_parser.add_argument("--eval-dir")
    swesmith_update_manifest_parser.add_argument("--quality-report", required=True)
    swesmith_update_manifest_parser.add_argument("--filtered-sft", required=True)
    swesmith_update_manifest_parser.add_argument("--splits-dir", required=True)
    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_coding_agent_cli_handler", False):
            root.removeHandler(handler)
            handler.close()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    stream_handler._coding_agent_cli_handler = True  # type: ignore[attr-defined]
    root.addHandler(stream_handler)
    if getattr(args, "log_file", None):
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        file_handler._coding_agent_cli_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
    root.setLevel(logging.DEBUG)


def _load_dotenv_into_process(path: str | Path) -> None:
    for key, value in parse_dotenv(Path(path)).items():
        if value and not os.environ.get(key):
            os.environ[key] = value


def _run_command(args: argparse.Namespace) -> int:
    """Run a single task using the ecosystem refactored agent.

    Exit codes: 2 = input/config error, 3 = artifact persistence error, 4 = runtime error.
    """
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        problem_path = Path(args.problem_statement_file)
        if not problem_path.is_file():
            raise ValueError("problem_statement_file must exist")
        task = BenchmarkTask(
            instance_id=args.instance_id,
            workspace=Path(args.workspace),
            problem_statement=problem_path.read_text(encoding="utf-8"),
            allowed_test_commands=tuple(args.allowed_tests or ()),
        )

        # Read templates
        template_dir = Path(__file__).resolve().parent / "config" / "templates"
        system_template = (template_dir / "system.j2").read_text(encoding="utf-8")
        instance_template = (template_dir / "instance.j2").read_text(encoding="utf-8")

        config = AgentConfig(
            system_template=system_template,
            instance_template=instance_template,
            step_limit=args.max_steps,
            time_limit_seconds=args.timeout_seconds,
            test_timeout_seconds=args.test_timeout_seconds,
            output_path=Path(args.output_dir),
        )

        if args.backend == "mock":
            model = ModelBackend(model_name=args.model or "mock-model")
        else:
            model_name = args.model or "openai/gpt-4o"
            model = ModelBackend(model_name=model_name)

        # Local executor (no Docker sandbox for plain 'run')
        from coding_agent.tools.executor import LocalToolExecutor
        executor = LocalToolExecutor(
            workspace=task.workspace,
            test_timeout_seconds=args.test_timeout_seconds,
        )

        agent = ToolAgent(model=model, executor=executor, config=config)
        summary = agent.run(task=task)

        print(f"Run {summary.run_id}: {summary.status.value}")
        return 0 if summary.status == RunStatus.SOLVED else 1
    except (ValueError,) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4


def _inspect_command(args: argparse.Namespace) -> int:
    """渲染一次运行的可读检查报告。

    inspect 依赖 summary.json 和 trajectory.jsonl 这两个审计核心文件；如果任一缺失，
    说明运行目录不完整，应当让调用方看到输入错误而不是空报告。
    """
    run_dir = Path(args.run_dir)
    summary_path = run_dir / "summary.json"
    trajectory_path = run_dir / "trajectory.jsonl"
    if not run_dir.is_dir():
        print("run directory does not exist", file=sys.stderr)
        return 2
    if not summary_path.is_file() or not trajectory_path.is_file():
        print("summary.json and trajectory.jsonl are required", file=sys.stderr)
        return 2
    print(render_inspect_report(load_summary(summary_path), load_trajectory(trajectory_path)))
    return 0


def _export_prediction_command(args: argparse.Namespace) -> int:
    """从已有运行目录重新导出 SWE-Bench prediction JSONL。"""
    try:
        export_prediction_from_run(args.run_dir, args.model_name, args.output)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 0


def _sandbox_register_command(args: argparse.Namespace) -> int:
    """注册调用方已经准备好的 Docker 基础镜像。

    这里会检查镜像存在，但不会构建镜像。是否官方兼容由调用方通过
    --official-compatible 显式声明，后续 swebench run 会强制检查这个标记。
    """
    try:
        register_base_image(
            args.registry,
            docker=DockerCli(),
            repo=args.repo,
            image=args.image,
            repo_path=args.repo_path,
            official_compatible=args.official_compatible,
            compatibility_source=args.compatibility_source,
            validation_command_template=args.validation_command_template,
        )
    except SandboxRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 0


def _sandbox_list_command(args: argparse.Namespace) -> int:
    """输出当前沙箱注册表，保持机器可读 JSON 格式。"""
    try:
        registry = SandboxRegistry.load(args.registry)
    except SandboxRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(registry.to_dict(), indent=2))
    return 0


def _swebench_prepare_command(args: argparse.Namespace) -> int:
    """Prepare official-style SWE-Bench runtime layers and one task environment."""
    logger.info("swebench prepare started: instance_id=%s dataset=%s output_dir=%s", args.instance_id, args.dataset, args.output_dir)
    try:
        prepare_official_swebench_runtime(
            dataset_path=args.dataset,
            instance_id=args.instance_id,
            docker=DockerCli(),
            output_dir=Path(args.output_dir),
            active_index_path=Path(".coding-agent/active-sandboxes.json"),
            build_missing=args.build_missing,
            replace_existing=args.replace_existing,
            arch=args.arch,
        )
    except (ValueError, SwebenchDatasetError, SandboxedRunInputError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4
    logger.info("swebench prepare completed: instance_id=%s output_dir=%s", args.instance_id, args.output_dir)
    return 0


def _swebench_run_command(args: argparse.Namespace) -> int:
    """Run one SWE-Bench task through an active official-style prepared environment."""
    logger.info("swebench run started: instance_id=%s dataset=%s output_dir=%s", args.instance_id, args.dataset, args.output_dir)
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        if args.backend == "mock":
            backend = MockBackend()
            model_name = args.model or "mock-model"
        else:
            config = load_model_config(model_override=args.model)
            backend = OpenAICompatibleBackend(config)
            model_name = config.model
        summary = run_prepared_swebench_runtime(
            dataset_path=args.dataset,
            instance_id=args.instance_id,
            docker=DockerCli(),
            backend=backend,
            budget=budget,
            model_name=model_name,
            output_dir=Path(args.output_dir),
            active_index_path=Path(".coding-agent/active-sandboxes.json"),
            include_pass_to_pass=args.include_pass_to_pass,
            cleanup=args.cleanup,
        )
        if summary.status is RunStatus.ERRORED:
            print(summary.error or "sandboxed run failed", file=sys.stderr)
            return 4
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
    logger.info("swebench run completed: instance_id=%s output_dir=%s", args.instance_id, args.output_dir)
    return 0


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


def _stage2_generate_teacher_trajectories_command(args: argparse.Namespace) -> int:
    """Run Stage 2 teacher SWE-smith trajectory generation pipeline."""
    try:
        _load_dotenv_into_process(".env.stage2")
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
            config = load_stage_model_config("stage2", dotenv_path=".env.stage2", model_override=args.model)
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
        sft_path = Path(args.sft_output)
        quality_report = sft_path.with_suffix(".quality.json")
        filtered_sft = sft_path.with_suffix(".filtered.jsonl")
        quality = run_quality_gate(
            runs_dir=str(output_dir),
            eval_dir=str(eval_dir),
            report_output=quality_report,
            filtered_sft_output=filtered_sft,
        )
        print(
            json.dumps(
                {
                    "output": args.sft_output,
                    "count": count,
                    "quality_report": str(quality.report_path),
                    "filtered_sft": str(quality.filtered_sft_path),
                    "accepted_count": quality.accepted_count,
                    "rejected_count": quality.rejected_count,
                },
                indent=2,
            )
        )
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


def _swebench_batch_run_command(args: argparse.Namespace) -> int:
    """Run every task in one or more SWE-Bench Lite datasets through prepare -> run."""
    logger.info("swebench batch-run started: datasets=%s output_dir=%s jobs=%s", args.datasets, args.output_dir, args.jobs)
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        if args.jobs <= 0:
            raise ValueError("jobs must be a positive integer")
        if args.backend == "mock":
            model_name = args.model or "mock-model"

            def backend_factory():
                return MockBackend()

        else:
            config = load_model_config(model_override=args.model)
            model_name = config.model

            def backend_factory():
                return OpenAICompatibleBackend(config)

        exit_code = run_official_swebench_batch(
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
        logger.info("swebench batch-run completed: output_dir=%s exit_code=%s", args.output_dir, exit_code)
        return exit_code
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


def _swebench_evaluate_command(args: argparse.Namespace) -> int:
    """Compute aggregate evaluation metrics from a batch output directory."""
    try:
        batch_dir = Path(args.batch_dir)
        results = load_evaluation_results(batch_dir)
        report = compute_aggregate_metrics(results)
        report["batch_dir"] = str(batch_dir)
        if args.json_output:
            output_text = json.dumps(report, indent=2, ensure_ascii=True)
        else:
            output_text = render_evaluation_report(report, batch_dir=str(batch_dir))
        if args.output:
            try:
                Path(args.output).write_text(output_text, encoding="utf-8")
            except OSError as exc:
                print(str(exc), file=sys.stderr)
                return 3
        else:
            print(output_text)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4
    return 0


def _swesmith_create_subset_command(args: argparse.Namespace) -> int:
    try:
        instances = load_huggingface_swesmith(split=args.split)
        languages_list = (
            [lang.strip() for lang in (args.languages or "").split(",") if lang.strip()]
            if args.languages
            else None
        )
        selected = create_subset_file(
            args.out,
            instances=instances,
            require_pr=args.require_pr,
            min_fail_to_pass=args.min_fail_to_pass,
            max_fail_to_pass=args.max_fail_to_pass,
            languages=languages_list,
            reference_path=args.reference_path,
        )
        print(json.dumps({"output": args.out, "count": len(selected)}, indent=2))
    except SwesmithDatasetError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 0


def _swesmith_run_subset_command(args: argparse.Namespace) -> int:
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        if args.backend == "mock":
            model_name = args.model or "mock-model"

            def backend_factory():
                return MockBackend()

        else:
            config = load_model_config(model_override=args.model)
            model_name = config.model

            def backend_factory():
                return OpenAICompatibleBackend(config)

        return run_swesmith_subset(
            subset_path=args.subset,
            docker=DockerCli(),
            backend_factory=backend_factory,
            budget=budget,
            model_name=model_name,
            output_dir=Path(args.output_dir),
            reference_path=args.reference_path,
            jobs=args.jobs,
            cleanup_images=args.cleanup_images,
        )
    except (ValueError, SwesmithDatasetError, SwesmithRuntimeError, MissingModelConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ArtifactPersistenceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4


def _swesmith_eval_command(args: argparse.Namespace) -> int:
    return run_official_eval(
        dataset_path=args.subset,
        predictions_path=args.predictions,
        run_id=args.run_id,
        workers=args.workers,
        reference_path=args.reference_path,
    )


def _swesmith_export_sft_command(args: argparse.Namespace) -> int:
    try:
        count = export_sft(runs_dir=args.runs, eval_dir=args.eval_dir, output=args.out, style=args.style)
        print(json.dumps({"output": args.out, "count": count}, indent=2))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _swesmith_quality_gate_command(args: argparse.Namespace) -> int:
    try:
        result = run_quality_gate(
            runs_dir=args.runs,
            eval_dir=args.eval_dir,
            report_output=args.out,
            filtered_sft_output=args.filtered_sft,
        )
        print(
            json.dumps(
                {
                    "report": str(result.report_path),
                    "filtered_sft": str(result.filtered_sft_path),
                    "accepted_count": result.accepted_count,
                    "rejected_count": result.rejected_count,
                },
                indent=2,
            )
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _swesmith_create_training_manifest_command(args: argparse.Namespace) -> int:
    try:
        languages = [lang.strip() for lang in (args.languages or "").split(",") if lang.strip()]
        result = create_training_manifest_from_input(
            input_path=args.input,
            out=args.out,
            splits_dir=args.splits_dir,
            languages=languages,
            reference_path=args.reference_path,
            sft_repos_file=args.sft_repos_file,
            easy_fail_to_pass_max=args.easy_fail_to_pass_max,
            medium_fail_to_pass_min=args.medium_fail_to_pass_min,
            medium_fail_to_pass_max=args.medium_fail_to_pass_max,
            sft_candidate_limit=args.sft_candidate_limit,
            grpo_dev_count=args.grpo_dev_count,
            heldout_count=args.heldout_count,
            seed=args.seed,
        )
        print(
            json.dumps(
                {
                    "manifest": str(result.manifest_path),
                    "splits_dir": str(result.splits_dir),
                    "summary": result.summary,
                },
                indent=2,
            )
        )
    except (SwesmithTrainingManifestError, SwesmithDatasetError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _swesmith_update_training_manifest_command(args: argparse.Namespace) -> int:
    try:
        result = update_training_manifest(
            manifest_path=args.manifest,
            quality_report_path=args.quality_report,
            filtered_sft_path=args.filtered_sft,
            splits_dir=args.splits_dir,
        )
        print(
            json.dumps(
                {
                    "manifest": str(result.manifest_path),
                    "splits_dir": str(result.splits_dir),
                    "summary": result.summary,
                },
                indent=2,
            )
        )
    except (SwesmithTrainingManifestError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _reject_legacy_swebench_operation(argv: Sequence[str] | None) -> int | None:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] != "swebench":
        return None
    legacy_operation = LEGACY_SWEBENCH_OPERATIONS.get(args[1])
    if legacy_operation is None:
        return None
    print(legacy_operation.error_message, file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口，返回退出码而不是直接 sys.exit，方便测试。"""
    legacy_exit_code = _reject_legacy_swebench_operation(argv)
    if legacy_exit_code is not None:
        return legacy_exit_code
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    _configure_logging(args)
    if args.command is None:
        parser.print_help()
        return 2
    if args.command == "run":
        return _run_command(args)
    if args.command == "inspect":
        return _inspect_command(args)
    if args.command == "export-prediction":
        return _export_prediction_command(args)
    if args.command == "sandbox":
        if getattr(args, "sandbox_command", None) == "register":
            return _sandbox_register_command(args)
        if getattr(args, "sandbox_command", None) == "list":
            return _sandbox_list_command(args)
        parser.error("sandbox subcommand is required")
        return 2
    if args.command == "stage1":
        if getattr(args, "stage1_command", None) == "run-qwen-vllm":
            return _stage1_run_qwen_vllm_command(args)
        parser.error("stage1 subcommand is required")
        return 2
    if args.command == "stage2":
        if getattr(args, "stage2_command", None) == "generate-teacher-trajectories":
            return _stage2_generate_teacher_trajectories_command(args)
        parser.error("stage2 subcommand is required")
        return 2
    if args.command == "swebench":
        if getattr(args, "swebench_command", None) == "prepare":
            return _swebench_prepare_command(args)
        if getattr(args, "swebench_command", None) == "run":
            return _swebench_run_command(args)
        if getattr(args, "swebench_command", None) == "batch-run":
            return _swebench_batch_run_command(args)
        if getattr(args, "swebench_command", None) == "evaluate":
            return _swebench_evaluate_command(args)
        parser.error("swebench subcommand is required")
        return 2
    if args.command == "swesmith":
        if getattr(args, "swesmith_command", None) == "create-subset":
            return _swesmith_create_subset_command(args)
        if getattr(args, "swesmith_command", None) == "run-subset":
            return _swesmith_run_subset_command(args)
        if getattr(args, "swesmith_command", None) == "eval":
            return _swesmith_eval_command(args)
        if getattr(args, "swesmith_command", None) == "export-sft":
            return _swesmith_export_sft_command(args)
        if getattr(args, "swesmith_command", None) == "quality-gate":
            return _swesmith_quality_gate_command(args)
        if getattr(args, "swesmith_command", None) == "create-training-manifest":
            return _swesmith_create_training_manifest_command(args)
        if getattr(args, "swesmith_command", None) == "update-training-manifest":
            return _swesmith_update_training_manifest_command(args)
        parser.error("swesmith subcommand is required")
        return 2
    parser.error(f"command {args.command!r} is not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
