from __future__ import annotations

import argparse
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
from coding_agent.models import RunBudget


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
    subparsers.add_parser("inspect", help="inspect a completed run directory")
    subparsers.add_parser("export-prediction", help="export prediction JSONL")
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
    parser.error(f"command {args.command!r} is not implemented yet")
    return 2
