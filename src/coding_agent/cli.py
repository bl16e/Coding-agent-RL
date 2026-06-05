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
    run_swebench_task,
)
from coding_agent.trajectory.summary import load_summary, load_trajectory, render_inspect_report


def build_parser() -> argparse.ArgumentParser:
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
    swebench_run_parser = swebench_subparsers.add_parser("run", help="run one SWE-Bench task in Docker")
    swebench_run_parser.add_argument("--dataset", required=True)
    swebench_run_parser.add_argument("--instance-id", required=True)
    swebench_run_parser.add_argument("--registry", required=True)
    swebench_run_parser.add_argument("--max-steps", type=int, required=True)
    swebench_run_parser.add_argument("--timeout-seconds", type=int, required=True)
    swebench_run_parser.add_argument("--test-timeout-seconds", type=int, required=True)
    swebench_run_parser.add_argument("--output-dir", required=True)
    swebench_run_parser.add_argument("--include-pass-to-pass", action="store_true")
    swebench_run_parser.add_argument("--model")
    swebench_run_parser.add_argument("--backend", choices=("openai-compatible", "mock"), default="openai-compatible")
    return parser


def _run_command(args: argparse.Namespace) -> int:
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
    try:
        registry = SandboxRegistry.load(args.registry)
    except SandboxRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(registry.to_dict(), indent=2))
    return 0


def _swebench_run_command(args: argparse.Namespace) -> int:
    try:
        budget = RunBudget(args.max_steps, args.timeout_seconds, args.test_timeout_seconds)
        task_record = load_task_record(args.dataset, args.instance_id)
        base_image = load_base_image_from_registry(args.registry, task_record.repo)
        if args.backend == "mock":
            backend = MockBackend()
            model_name = args.model or "mock-model"
        else:
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
