from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class SwesmithDatasetError(ValueError):
    """Raised when SWE-smith subset input is invalid."""


REQUIRED_FIELDS = ("instance_id", "problem_statement", "FAIL_TO_PASS")

LANGUAGE_MODULES: dict[str, str] = {
    "python": "swesmith.profiles.python",
    "c": "swesmith.profiles.c",
    "cpp": "swesmith.profiles.cpp",
    "csharp": "swesmith.profiles.csharp",
    "go": "swesmith.profiles.golang",
    "java": "swesmith.profiles.java",
    "javascript": "swesmith.profiles.javascript",
    "php": "swesmith.profiles.php",
    "ruby": "swesmith.profiles.ruby",
    "rust": "swesmith.profiles.rust",
    "typescript": "swesmith.profiles.typescript",
}


def validate_instance(instance: dict[str, Any]) -> dict[str, Any]:
    for field in REQUIRED_FIELDS:
        if not instance.get(field):
            raise SwesmithDatasetError(f"{field} is required")
    if not isinstance(instance["FAIL_TO_PASS"], list):
        raise SwesmithDatasetError("FAIL_TO_PASS must be a list")
    if "PASS_TO_PASS" in instance and not isinstance(instance["PASS_TO_PASS"], list):
        raise SwesmithDatasetError("PASS_TO_PASS must be a list")
    return dict(instance)


def _load_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SwesmithDatasetError("json subset must be an array")
    return [validate_instance(item) for item in payload]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise SwesmithDatasetError(f"jsonl line {line_number} must be an object")
        rows.append(validate_instance(payload))
    return rows


def load_subset(path: str | Path) -> list[dict[str, Any]]:
    subset_path = Path(path)
    if not subset_path.is_file():
        raise SwesmithDatasetError(f"subset file does not exist: {subset_path}")
    if subset_path.suffix == ".jsonl":
        rows = _load_jsonl(subset_path)
    elif subset_path.suffix == ".json":
        rows = _load_json(subset_path)
    else:
        raise SwesmithDatasetError("subset path must end with .json or .jsonl")
    if not rows:
        raise SwesmithDatasetError("subset must contain at least one instance")
    return rows


def _get_language_repo_ids(
    languages: list[str],
    *,
    reference_path: str | Path | None = None,
) -> set[str]:
    """Build set of repo identifiers for given languages from SWE-smith profile files.

    Parses the profile source files (e.g. ``swesmith/profiles/python.py``) directly
    using regex -- no SWE-smith import is needed.  Each concrete profile class defines
    ``owner``, ``repo``, and ``commit`` string fields.  From those we build the
    ``repo_name`` key (``{owner}__{repo}.{commit[:8]}``) that the registry uses for
    instance lookup.
    """
    import re

    if not languages:
        return set()

    # Map language name -> relative path under the SWE-smith checkout.
    LANGUAGE_FILES: dict[str, str] = {
        "python": "swesmith/profiles/python.py",
        "c": "swesmith/profiles/c.py",
        "cpp": "swesmith/profiles/cpp.py",
        "csharp": "swesmith/profiles/csharp.py",
        "go": "swesmith/profiles/golang.py",
        "java": "swesmith/profiles/java.py",
        "javascript": "swesmith/profiles/javascript.py",
        "php": "swesmith/profiles/php.py",
        "ruby": "swesmith/profiles/ruby.py",
        "rust": "swesmith/profiles/rust.py",
        "typescript": "swesmith/profiles/typescript.py",
    }

    unknown = [lang for lang in languages if lang.lower() not in LANGUAGE_FILES]
    if unknown:
        raise SwesmithDatasetError(
            f"unsupported language(s): {', '.join(unknown)}. "
            f"supported: {', '.join(sorted(LANGUAGE_FILES))}"
        )

    if reference_path is None:
        raise SwesmithDatasetError(
            "cannot determine language repo ids: pass --reference-path to the SWE-smith checkout"
        )

    root = Path(reference_path)
    if not root.is_dir():
        raise SwesmithDatasetError(f"SWE-smith checkout does not exist: {root}")

    # Patterns for extracting owner, repo, commit from profile dataclass definitions.
    _OWNER_RE = re.compile(r'^\s+owner:\s*(?:str\s*=\s*)?["\'](.+?)["\']')
    _REPO_RE = re.compile(r'^\s+repo:\s*(?:str\s*=\s*)?["\'](.+?)["\']')
    _COMMIT_RE = re.compile(r'^\s+commit:\s*(?:str\s*=\s*)?["\'](.+?)["\']')

    repo_ids: set[str] = set()

    for lang in languages:
        rel_path = LANGUAGE_FILES[lang.lower()]
        abs_path = root / rel_path
        if not abs_path.is_file():
            raise SwesmithDatasetError(
                f"profile file not found for language '{lang}': {abs_path}"
            )
        source = abs_path.read_text(encoding="utf-8")

        owner: str | None = None
        repo: str | None = None
        for line in source.splitlines():
            m = _OWNER_RE.match(line)
            if m:
                owner = m.group(1)
                continue
            m = _REPO_RE.match(line)
            if m:
                repo = m.group(1)
                continue
            m = _COMMIT_RE.match(line)
            if m and owner and repo:
                commit = m.group(1)
                repo_ids.add(f"{owner}__{repo}.{commit[:8]}")
                owner = None
                repo = None

    if not repo_ids:
        raise SwesmithDatasetError(
            f"no repository profiles found for language(s): {', '.join(languages)}"
        )

    return repo_ids


def _repo_key(instance: dict[str, Any]) -> str:
    """Derive the registry lookup key from an instance dict.

    Mirrors the logic in ``swesmith.profiles.Registry.get_from_inst``: the ``repo``
    field is preferred; otherwise the instance_id is stripped after the last dot.
    """
    return str(instance.get("repo") or str(instance["instance_id"]).rsplit(".", 1)[0])


def filter_instances(
    instances: Iterable[dict[str, Any]],
    *,
    require_pr: bool,
    min_fail_to_pass: int,
    max_fail_to_pass: int,
    language_repo_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw in instances:
        instance = validate_instance(dict(raw))
        fail_to_pass = instance["FAIL_TO_PASS"]
        if require_pr and ".pr_" not in instance["instance_id"]:
            continue
        if len(fail_to_pass) < min_fail_to_pass:
            continue
        if len(fail_to_pass) > max_fail_to_pass:
            continue
        if language_repo_ids is not None and _repo_key(instance) not in language_repo_ids:
            continue
        selected.append(instance)
    return selected


def create_subset_file(
    output: str | Path,
    *,
    instances: Iterable[dict[str, Any]],
    require_pr: bool = True,
    min_fail_to_pass: int = 2,
    max_fail_to_pass: int = 5,
    languages: list[str] | None = None,
    reference_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    if min_fail_to_pass < 0 or max_fail_to_pass < min_fail_to_pass:
        raise SwesmithDatasetError("fail-to-pass bounds are invalid")
    language_repo_ids: set[str] | None = None
    if languages:
        language_repo_ids = _get_language_repo_ids(languages, reference_path=reference_path)
    selected = filter_instances(
        instances,
        require_pr=require_pr,
        min_fail_to_pass=min_fail_to_pass,
        max_fail_to_pass=max_fail_to_pass,
        language_repo_ids=language_repo_ids,
    )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(selected, indent=2, ensure_ascii=True), encoding="utf-8")
    return selected


def load_huggingface_swesmith(split: str = "train") -> list[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SwesmithDatasetError("datasets package is required for Hugging Face loading") from exc
    return [dict(item) for item in load_dataset("SWE-bench/SWE-smith", split=split)]
