from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re
from typing import Any

from coding_agent.models import RepoSpecReviewStatus, RepoVersionSpec


class MissingRepoSpecError(ValueError):
    """Raised when source-backed repo/version metadata is unavailable."""


class RepoSpecRegistry:
    """Lookup boundary for source-backed SWE-Bench repo/version metadata."""

    def __init__(self, specs: Iterable[RepoVersionSpec] = ()) -> None:
        self._specs = {(spec.repo, spec.version): spec for spec in specs}

    def get(self, repo: str, version: str) -> RepoVersionSpec | None:
        return self._specs.get((repo, version))

    def audited_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._specs))

    def require(self, repo: str, version: str) -> RepoVersionSpec:
        spec = self.get(repo, version)
        if spec is None:
            raise MissingRepoSpecError(f"missing source-backed metadata for {repo}@{version}")
        if spec.review_status is not RepoSpecReviewStatus.SOURCE_BACKED:
            raise MissingRepoSpecError(f"repo/version metadata is not source-backed: {repo}@{version}")
        return spec


AUDIT_SOURCE_REFERENCE = "specs/003-agent-runtime-refactor/runtime-image-audit.md"
UPSTREAM_PYTHON_CONSTANTS_REFERENCE = "SWE-bench/swebench/harness/constants/python.py"
SOURCE_BACKED_REFERENCE = f"{AUDIT_SOURCE_REFERENCE}; {UPSTREAM_PYTHON_CONSTANTS_REFERENCE}"

TEST_DJANGO = "./tests/runtests.py --verbosity 2 --settings=test_sqlite --parallel 1"
TEST_PYTEST = "pytest -rA"
TEST_ASTROPY_PYTEST = "pytest -rA -vv -o console_output_style=classic --tb=no"
TEST_SEABORN = "pytest --no-header -rA"
TEST_SPHINX = "tox --current-env -epy39 -v --"
TEST_SYMPY = "PYTHONWARNINGS='ignore::UserWarning,ignore::SyntaxWarning' bin/test -C --verbose"

REPO_DEFAULT_METADATA: dict[str, dict[str, Any]] = {
    "astropy/astropy": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .[test] --verbose",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "django/django": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "test_command": TEST_DJANGO,
    },
    "marshmallow-code/marshmallow": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e '.[dev]'",),
        "test_command": TEST_PYTEST,
    },
    "matplotlib/matplotlib": {
        "python_version": "3.11",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "mwaskom/seaborn": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .[dev]",),
        "pip_packages": ("pytest",),
        "test_command": TEST_SEABORN,
    },
    "pallets/flask": {
        "python_version": "3.11",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "psf/requests": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "pvlib/pvlib-python": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "pydata/xarray": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "pydicom/pydicom": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "pylint-dev/astroid": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "pylint-dev/pylint": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "pytest-dev/pytest": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "test_command": TEST_PYTEST,
    },
    "pyvista/pyvista": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    "scikit-learn/scikit-learn": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -v --no-use-pep517 --no-build-isolation -e .",),
        "pip_packages": ("cython", "setuptools", "numpy", "scipy"),
        "test_command": TEST_PYTEST,
    },
    "sphinx-doc/sphinx": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .[test]",),
        "pip_packages": ("tox==4.16.0", "tox-current-env==0.0.11", "Jinja2==3.0.3"),
        "test_command": TEST_SPHINX,
    },
    "sqlfluff/sqlfluff": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "test_command": TEST_PYTEST,
    },
    "sympy/sympy": {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("mpmath==1.3.0",),
        "test_command": TEST_SYMPY,
    },
}

REPO_VERSION_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("django/django", "3.0"): {
        "python_version": "3.6",
        "install_commands": ("python -m pip install -e .",),
        "test_command": TEST_DJANGO,
    },
    ("pytest-dev/pytest", "6.0"): {
        "python_version": "3.9",
        "install_commands": ("python -m pip install -e .",),
        "pip_packages": ("pytest",),
        "test_command": TEST_PYTEST,
    },
    ("astropy/astropy", "1.3"): {
        "python_version": "3.6",
        "install_commands": ("python -m pip install -e .[test] --verbose",),
        "pip_packages": ("pytest",),
        "test_command": TEST_ASTROPY_PYTEST,
    },
}


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
    audited_pairs = set(pairs)
    specs = []
    for pair, metadata in REPO_VERSION_OVERRIDES.items():
        if pair not in audited_pairs:
            continue
        repo, version = pair
        specs.append(
            RepoVersionSpec(
                repo=repo,
                version=version,
                language="py",
                test_command=str(metadata["test_command"]),
                source_reference=SOURCE_BACKED_REFERENCE,
                review_status=RepoSpecReviewStatus.SOURCE_BACKED,
                python_version=str(metadata["python_version"]) if metadata.get("python_version") else None,
                packages=tuple(metadata.get("packages", ())),
                pip_packages=tuple(metadata.get("pip_packages", ())),
                install_commands=tuple(metadata.get("install_commands", ())),
                docker_specs=dict(metadata.get("docker_specs", {})),
            )
        )
    for repo, version in pairs:
        if any((spec.repo, spec.version) == (repo, version) for spec in specs):
            continue
        metadata = REPO_DEFAULT_METADATA.get(repo)
        if metadata is None:
            continue
        specs.append(
            RepoVersionSpec(
                repo=repo,
                version=version,
                language="py",
                test_command=str(metadata["test_command"]),
                source_reference=SOURCE_BACKED_REFERENCE,
                review_status=RepoSpecReviewStatus.SOURCE_BACKED,
                python_version=str(metadata["python_version"]) if metadata.get("python_version") else None,
                packages=tuple(metadata.get("packages", ())),
                pip_packages=tuple(metadata.get("pip_packages", ())),
                install_commands=tuple(metadata.get("install_commands", ())),
                docker_specs=dict(metadata.get("docker_specs", {})),
            )
        )
    return RepoSpecRegistry(specs)


DEFAULT_REPO_SPECS = load_audit_repo_specs()
