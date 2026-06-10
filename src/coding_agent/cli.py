from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from coding_agent.agent import ArtifactPersistenceError, create_task_from_paths, run_task
from coding_agent.model_backends.mock import MockBackend
from coding_agent.model_backends.openai_compatible import (
    MissingModelConfigError,
    OpenAICompatibleBackend,
    load_model_config,
)
from coding_agent.models import RunBudget, RunStatus
from coding_agent.sandbox.docker_cli import DockerCli
from coding_agent.sandbox.registry import SandboxRegistry, SandboxRegistryError, register_base_image
from coding_agent.swebench.dataset import SwebenchDatasetError, load_task_record
from coding_agent.swebench.prediction import export_prediction_from_run
from coding_agent.swebench.sandbox_run import (
    SandboxedRunInputError,
    SandboxedRunRuntimeError,
    load_base_image_from_registry,
    parse_instance_id_file,
    run_swebench_task,
    run_swebench_tasks,
)
from coding_agent.trajectory.summary import load_summary, load_trajectory, render_inspect_report


def build_parser() -> argparse.ArgumentParser:
    """构造完整 CLI。

    这个项目刻意把 argparse 留在最外层：子命令只收集字符串/数字参数，真正的领域
    校验会下沉到 models、registry、dataset 和 sandbox_run，便于测试库函数。
    """
    parser = argparse.ArgumentParser(prog="coding-agent")
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
    swebench_parser = subparsers.add_parser("swebench", help="SWE-Bench commands")
    swebench_subparsers = swebench_parser.add_subparsers(dest="swebench_command")
    swebench_run_parser = swebench_subparsers.add_parser("run", help="run SWE-Bench task(s) in Docker")
    swebench_run_parser.add_argument("--dataset", required=True)
    instance_source = swebench_run_parser.add_mutually_exclusive_group(required=True)
    instance_source.add_argument("--instance-id", action="append", dest="instance_ids")
    instance_source.add_argument("--instance-id-file")
    swebench_run_parser.add_argument("--registry", required=True)
    swebench_run_parser.add_argument("--jobs", type=int, default=1)
    swebench_run_parser.add_argument("--max-steps", type=int, required=True)
    swebench_run_parser.add_argument("--timeout-seconds", type=int, required=True)
    swebench_run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    swebench_run_parser.add_argument("--output-dir", required=True)
    swebench_run_parser.add_argument("--include-pass-to-pass", action="store_true")
    swebench_run_parser.add_argument("--model")
    swebench_run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    return parser


def _run_command(args: argparse.Namespace) -> int:
    """运行已准备好的本地工作区任务。

    退出码约定：
    2 表示用户输入或配置错误，3 表示产物写入失败，4 表示运行期未知错误。
    Docker/SWE-Bench 路径也沿用这个约定，方便 CI 脚本统一处理。
    """
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        task = create_task_from_paths(
            instance_id=args.instance_id,
            workspace=Path(args.workspace),
            problem_statement_file=Path(args.problem_statement_file),
            allowed_test_commands=tuple(args.allowed_tests or ()),
        )
        if args.backend == "mock":
            backend = MockBackend()
            model_name = args.model or "mock-model"
        else:
            # 真实后端配置从环境或 .env 读取；CLI 层只允许 --model 覆盖模型名，
            # 不在命令行暴露 API_KEY，避免 shell history 泄露敏感信息。
            config = load_model_config(model_override=args.model)
            backend = OpenAICompatibleBackend(config)
            model_name = config.model
        run_task(
            task=task,
            budget=budget,
            backend=backend,
            model_name=model_name,
            output_dir=Path(args.output_dir),
        )
    except (ValueError, MissingModelConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ArtifactPersistenceError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 4
    return 0


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


def _swebench_run_command(args: argparse.Namespace) -> int:
    """运行一个 parquet 数据集里的 SWE-Bench 实例。

    这个子命令把数据集、注册表、模型后端和 Docker CLI 拼接起来；具体容器生命周期
    和验证命令构造分别委托给 sandbox_run/validation，避免 CLI 承担业务编排细节。
    """
    try:
        instance_ids = tuple(args.instance_ids or parse_instance_id_file(args.instance_id_file))
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        if args.jobs <= 0:
            raise ValueError("jobs must be a positive integer")
        if len(instance_ids) == 1:
            task_record = load_task_record(args.dataset, instance_ids[0])
            base_image = load_base_image_from_registry(args.registry, task_record.repo)
            if args.backend == "mock":
                backend = MockBackend()
                model_name = args.model or "mock-model"
            else:
                # 与本地 run 保持同样的模型配置路径，确保两种执行位置只差工具执行器。
                config = load_model_config(model_override=args.model)
                backend = OpenAICompatibleBackend(config)
                model_name = config.model
            summary = run_swebench_task(
                task_record=task_record,
                base_image=base_image,
                docker=DockerCli(),
                backend=backend,
                budget=budget,
                model_name=model_name,
                output_dir=Path(args.output_dir),
                include_pass_to_pass=args.include_pass_to_pass,
            )
            if summary.status is RunStatus.ERRORED:
                print(summary.error or "sandboxed run failed", file=sys.stderr)
                return 4
        else:
            if args.backend == "mock":
                model_name = args.model or "mock-model"

                def backend_factory():
                    return MockBackend()

            else:
                config = load_model_config(model_override=args.model)
                model_name = config.model

                def backend_factory():
                    return OpenAICompatibleBackend(config)

            return run_swebench_tasks(
                dataset_path=args.dataset,
                instance_ids=instance_ids,
                registry_path=args.registry,
                docker=DockerCli(),
                backend_factory=backend_factory,
                budget=budget,
                model_name=model_name,
                output_dir=Path(args.output_dir),
                jobs=args.jobs,
                include_pass_to_pass=args.include_pass_to_pass,
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
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口，返回退出码而不是直接 sys.exit，方便测试。"""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
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
    if args.command == "swebench":
        if getattr(args, "swebench_command", None) == "run":
            return _swebench_run_command(args)
        parser.error("swebench subcommand is required")
        return 2
    parser.error(f"command {args.command!r} is not implemented yet")
    return 2
