from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re

from coding_agent.models import RepoSpecReviewStatus, RepoVersionSpec


class MissingRepoSpecError(ValueError):
    """Raised when source-backed repo/version metadata is unavailable."""


class RepoSpecRegistry:
    """Lookup boundary for source-backed SWE-Bench repo/version metadata."""

    def __init__(self, specs: Iterable[RepoVersionSpec] = ()) -> None:
        self._specs = {(spec.repo, spec.version): spec for spec in specs}

    def get(self, repo: str, version: str) -> RepoVersionSpec | None:
        return self._specs.get((repo, version))

    def require(self, repo: str, version: str) -> RepoVersionSpec:
        spec = self.get(repo, version)
        if spec is None:
            raise MissingRepoSpecError(f"missing source-backed metadata for {repo}@{version}")
        if spec.review_status is not RepoSpecReviewStatus.SOURCE_BACKED:
            raise MissingRepoSpecError(f"repo/version metadata is not source-backed: {repo}@{version}")
        return spec


AUDIT_SOURCE_REFERENCE = "specs/003-agent-runtime-refactor/runtime-image-audit.md"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _audit_path() -> Path:
    return _project_root() / AUDIT_SOURCE_REFERENCE


def _parse_supported_pairs(audit_text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    in_table = False
    for line in audit_text.splitlines():
        if line.strip() == "## Supported Repository Versions":
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        match = re.match(r"\| `([^`]+)` \| `([^`]+)` \| \d+ \|", line)
        if match:
            pairs.append((match.group(1), match.group(2)))
    return pairs


def load_audit_repo_specs(audit_path: Path | None = None) -> RepoSpecRegistry:
    path = audit_path or _audit_path()
    if not path.is_file():
        return RepoSpecRegistry()
    pairs = _parse_supported_pairs(path.read_text(encoding="utf-8"))
    specs = [
        RepoVersionSpec(
            repo=repo,
            version=version,
            language="py",
            install_commands=("python -m pip install -e .",),
            test_command="python -m pytest",
            source_reference=AUDIT_SOURCE_REFERENCE,
            review_status=RepoSpecReviewStatus.SOURCE_BACKED,
        )
        for repo, version in pairs
    ]
    return RepoSpecRegistry(specs)


DEFAULT_REPO_SPECS = load_audit_repo_specs()
