import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


BATCH_NAME_RE = re.compile(r"^sft_candidate_batch_(\d+)\.json$")


@dataclass(frozen=True)
class BatchRun:
    batch_path: Path
    run_id: str
    quality_path: Path
    command: list[str]
    skip: bool


def _batch_suffix(path: Path) -> str:
    match = BATCH_NAME_RE.match(path.name)
    if not match:
        raise ValueError(f"unexpected batch filename: {path.name}")
    return match.group(1)


def _build_command(
    *,
    batch_path: Path,
    run_id: str,
    output_root: Path,
    sft_root: Path,
    reference_path: Path,
    max_steps: int,
    timeout_seconds: int,
    test_timeout_seconds: int,
    jobs: int,
    eval_workers: int,
) -> list[str]:
    return [
        "coding-agent",
        "stage2",
        "generate-teacher-trajectories",
        "--subset",
        str(batch_path),
        "--output-dir",
        str(output_root / run_id),
        "--reference-path",
        str(reference_path),
        "--max-steps",
        str(max_steps),
        "--timeout-seconds",
        str(timeout_seconds),
        "--test-timeout-seconds",
        str(test_timeout_seconds),
        "--jobs",
        str(jobs),
        "--eval-workers",
        str(eval_workers),
        "--run-id",
        run_id,
        "--sft-output",
        str(sft_root / f"{run_id}.jsonl"),
    ]


def plan_batches(
    *,
    batch_dir: str | Path,
    run_prefix: str,
    output_root: str | Path,
    sft_root: str | Path,
    reference_path: str | Path,
    max_steps: int,
    timeout_seconds: int,
    test_timeout_seconds: int,
    jobs: int,
    eval_workers: int,
) -> list[BatchRun]:
    batch_root = Path(batch_dir)
    output_root = Path(output_root)
    sft_root = Path(sft_root)
    reference_path = Path(reference_path)
    batches = sorted(path for path in batch_root.glob("sft_candidate_batch_*.json") if BATCH_NAME_RE.match(path.name))
    plan: list[BatchRun] = []
    for batch_path in batches:
        suffix = _batch_suffix(batch_path)
        run_id = f"{run_prefix}{suffix}"
        quality_path = sft_root / f"{run_id}.quality.json"
        plan.append(
            BatchRun(
                batch_path=batch_path,
                run_id=run_id,
                quality_path=quality_path,
                command=_build_command(
                    batch_path=batch_path,
                    run_id=run_id,
                    output_root=output_root,
                    sft_root=sft_root,
                    reference_path=reference_path,
                    max_steps=max_steps,
                    timeout_seconds=timeout_seconds,
                    test_timeout_seconds=test_timeout_seconds,
                    jobs=jobs,
                    eval_workers=eval_workers,
                ),
                skip=quality_path.exists(),
            )
        )
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage 2 SWE-smith SFT candidate batches with resume support.")
    parser.add_argument("--batch-dir", default="data/splits_sft8000_top39/batches_20")
    parser.add_argument("--run-prefix", default="stage2_sft8000_top39_b")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--sft-root", default="sft_data")
    parser.add_argument("--reference-path", default="Reference/SWE-smith")
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--test-timeout-seconds", type=int, default=180)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--eval-workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="print planned commands without executing them")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sft_root = Path(args.sft_root)
    sft_root.mkdir(parents=True, exist_ok=True)
    plan = plan_batches(
        batch_dir=args.batch_dir,
        run_prefix=args.run_prefix,
        output_root=args.output_root,
        sft_root=sft_root,
        reference_path=args.reference_path,
        max_steps=args.max_steps,
        timeout_seconds=args.timeout_seconds,
        test_timeout_seconds=args.test_timeout_seconds,
        jobs=args.jobs,
        eval_workers=args.eval_workers,
    )
    if not plan:
        raise ValueError(f"no batch files found in {args.batch_dir}")

    for item in plan:
        if item.skip:
            print(f"SKIP {item.run_id}")
            continue
        print(f"RUN {item.run_id}")
        print(" ".join(item.command))
        if not args.dry_run:
            completed = subprocess.run(item.command)
            if completed.returncode != 0:
                return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
