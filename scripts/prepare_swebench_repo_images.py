from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple, Sequence


DEFAULT_DATASETS = (
    Path("data/dev-00000-of-00001.parquet"),
    Path("data/test-00000-of-00001.parquet"),
)
DEFAULT_IMAGE_PREFIX = "coding-agent-swebench-repo"
DEFAULT_MANIFEST = Path(".coding-agent/repo-base-images.json")
DEFAULT_REPO_PATH = "/workspace/repo"
DEFAULT_BASE_IMAGE = "ubuntu:22.04"

Runner = Callable[..., subprocess.CompletedProcess[str]]


class RepoImageResult(NamedTuple):
    repo: str
    image: str
    repo_path: str
    status: str
    built_at: str | None
    error: str | None = None


def load_unique_repos(dataset_paths: Sequence[str | Path]) -> tuple[str, ...]:
    repos: set[str] = set()
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required to read parquet datasets") from exc

    for dataset_path in dataset_paths:
        path = Path(dataset_path)
        if not path.is_file():
            raise ValueError(f"dataset does not exist: {path}")
        table = pq.read_table(path, columns=["repo"])
        for row in table.to_pylist():
            repo = str(row.get("repo") or "").strip()
            if repo:
                repos.add(repo)
    if not repos:
        raise ValueError("no repos found in dataset")
    return tuple(sorted(repos))


def image_name_for_repo(repo: str, image_prefix: str = DEFAULT_IMAGE_PREFIX) -> str:
    normalized = repo.strip().lower().replace("/", "-").replace("_", "-")
    if not normalized or "-" not in normalized:
        raise ValueError(f"repo must be in owner/name form: {repo!r}")
    return f"{image_prefix}-{normalized}:latest"


def image_exists(image: str, *, runner: Runner = subprocess.run) -> bool:
    completed = runner(
        ["docker", "image", "inspect", image],
        text=True,
        capture_output=True,
        check=False,
    )
    return int(completed.returncode) == 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dockerfile_text(*, base_image: str, repo_path: str) -> str:
    return f"""FROM {base_image}
ARG REPO
RUN apt-get update \\
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \\
        git \\
        ca-certificates \\
        curl \\
        build-essential \\
        patch \\
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /workspace
RUN git clone https://github.com/${{REPO}}.git {repo_path} \\
    && cd {repo_path} \\
    && git fetch --all --tags --prune \\
    && git config --global --add safe.directory {repo_path}
WORKDIR {repo_path}
"""


def _repo_context_dir(root: Path, repo: str) -> Path:
    return root / repo.replace("/", "-").replace("_", "-")


def _write_dockerfile(context_dir: Path, *, base_image: str, repo_path: str) -> None:
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "Dockerfile").write_text(_dockerfile_text(base_image=base_image, repo_path=repo_path), encoding="utf-8")


def build_repo_image(
    repo: str,
    image: str,
    *,
    context_root: Path,
    runner: Runner = subprocess.run,
    repo_path: str = DEFAULT_REPO_PATH,
    base_image: str = DEFAULT_BASE_IMAGE,
    dry_run: bool = False,
) -> RepoImageResult:
    context_dir = _repo_context_dir(context_root, repo)
    _write_dockerfile(context_dir, base_image=base_image, repo_path=repo_path)
    command = ["docker", "build", "--build-arg", f"REPO={repo}", "-t", image, str(context_dir)]
    if dry_run:
        print(" ".join(command))
        return RepoImageResult(repo, image, repo_path, "dry-run", None)

    completed = runner(command, text=True, capture_output=True, check=False)
    if int(completed.returncode) != 0:
        error = (completed.stderr or completed.stdout or "docker build failed").strip()
        return RepoImageResult(repo, image, repo_path, "failed", None, error)
    return RepoImageResult(repo, image, repo_path, "built", _now_iso())


def _process_repo(
    repo: str,
    *,
    context_root: Path,
    runner: Runner,
    image_prefix: str,
    repo_path: str,
    base_image: str,
    build_missing: bool,
    force_rebuild: bool,
    dry_run: bool,
) -> RepoImageResult:
    image = image_name_for_repo(repo, image_prefix)
    if dry_run:
        if not build_missing and not force_rebuild:
            print(" ".join(["docker", "image", "inspect", image]))
            return RepoImageResult(repo, image, repo_path, "dry-run", None)
        return build_repo_image(
            repo,
            image,
            context_root=context_root,
            runner=runner,
            repo_path=repo_path,
            base_image=base_image,
            dry_run=True,
        )

    exists = image_exists(image, runner=runner)
    if exists and not force_rebuild:
        return RepoImageResult(repo, image, repo_path, "existing", _now_iso())
    if not build_missing and not force_rebuild:
        return RepoImageResult(repo, image, repo_path, "missing", None)
    return build_repo_image(
        repo,
        image,
        context_root=context_root,
        runner=runner,
        repo_path=repo_path,
        base_image=base_image,
    )


def write_manifest(path: str | Path, results: Sequence[RepoImageResult]) -> None:
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "coding-agent.swebench.repo-base-images.v1",
        "generated_at": _now_iso(),
        "images": [
            {
                "repo": result.repo,
                "image": result.image,
                "repo_path": result.repo_path,
                "status": result.status,
                "built_at": result.built_at,
                **({"error": result.error} if result.error else {}),
            }
            for result in results
        ],
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def prepare_repo_images(
    repos: Sequence[str],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    runner: Runner = subprocess.run,
    image_prefix: str = DEFAULT_IMAGE_PREFIX,
    repo_path: str = DEFAULT_REPO_PATH,
    base_image: str = DEFAULT_BASE_IMAGE,
    build_missing: bool = True,
    force_rebuild: bool = False,
    jobs: int = 1,
    dockerfile_out: str | Path | None = None,
    dry_run: bool = False,
) -> tuple[RepoImageResult, ...]:
    if jobs <= 0:
        raise ValueError("jobs must be a positive integer")
    unique_repos = tuple(dict.fromkeys(str(repo).strip() for repo in repos if str(repo).strip()))
    if not unique_repos:
        raise ValueError("at least one repo is required")

    with tempfile.TemporaryDirectory() as tmp:
        context_root = Path(dockerfile_out) if dockerfile_out else Path(tmp)
        context_root.mkdir(parents=True, exist_ok=True)

        def run_one(repo: str) -> RepoImageResult:
            return _process_repo(
                repo,
                context_root=context_root,
                runner=runner,
                image_prefix=image_prefix,
                repo_path=repo_path,
                base_image=base_image,
                build_missing=build_missing,
                force_rebuild=force_rebuild,
                dry_run=dry_run,
            )

        if jobs == 1:
            results = tuple(run_one(repo) for repo in unique_repos)
        else:
            with ThreadPoolExecutor(max_workers=jobs) as executor:
                results = tuple(executor.map(run_one, unique_repos))

    if not dry_run:
        write_manifest(manifest_path, results)
    return results


def _filter_repos(all_repos: Sequence[str], selected_repos: Sequence[str] | None) -> tuple[str, ...]:
    if not selected_repos:
        return tuple(all_repos)
    available = set(all_repos)
    requested = tuple(dict.fromkeys(selected_repos))
    missing = [repo for repo in requested if repo not in available]
    if missing:
        raise ValueError("repo not found in dataset: " + ", ".join(missing))
    return requested


def _print_summary(results: Sequence[RepoImageResult]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    print("summary: " + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))
    failed = [result.repo for result in results if result.status == "failed"]
    if failed:
        print("failed: " + ", ".join(failed))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare SWE-Bench Lite repo source base Docker images.")
    parser.add_argument("--dataset", action="append", dest="datasets", help="SWE-Bench parquet dataset path. May be repeated.")
    parser.add_argument("--check-only", action="store_true", help="Detect existing and missing images without building.")
    parser.add_argument("--build-missing", action="store_true", help="Build missing images. This is the default.")
    parser.add_argument("--force-rebuild", action="store_true", help="Build images even when they already exist.")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--image-prefix", default=DEFAULT_IMAGE_PREFIX)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--repo", action="append", dest="repos", help="Limit processing to one repo. May be repeated.")
    parser.add_argument("--dockerfile-out", help="Directory where generated Dockerfile contexts should be kept.")
    parser.add_argument("--dry-run", action="store_true", help="Print Docker commands without invoking Docker or writing manifest.")
    return parser


def main(argv: Sequence[str] | None = None, *, runner: Runner = subprocess.run) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        datasets = tuple(Path(path) for path in (args.datasets or DEFAULT_DATASETS))
        all_repos = load_unique_repos(datasets)
        repos = _filter_repos(all_repos, args.repos)
        build_missing = not args.check_only
        results = prepare_repo_images(
            repos,
            manifest_path=args.manifest,
            runner=runner,
            image_prefix=args.image_prefix,
            build_missing=build_missing,
            force_rebuild=args.force_rebuild,
            jobs=args.jobs,
            dockerfile_out=args.dockerfile_out,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    _print_summary(results)
    return 4 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
