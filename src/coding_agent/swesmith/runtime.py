from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_agent.swesmith.compat import install_windows_resource_shim


class SwesmithRuntimeError(RuntimeError):
    """Raised when SWE-smith official runtime setup cannot proceed."""


@dataclass(frozen=True)
class SwesmithPreparedContainer:
    instance_id: str
    container_name: str
    repo_path: str
    profile_key: str
    raw_container: Any
    raw_profile: Any


def import_swesmith(reference_path: str | Path | None = None) -> Any:
    install_windows_resource_shim()
    if reference_path is not None:
        root = Path(reference_path)
        if not root.exists():
            raise SwesmithRuntimeError(f"SWE-smith checkout does not exist: {root}")
        root_text = str(root.resolve())
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
    try:
        return importlib.import_module("swesmith")
    except ImportError as exc:
        raise SwesmithRuntimeError(
            "SWE-smith cannot be imported; pass --reference-path or set PYTHONPATH to the SWE-smith checkout"
        ) from exc


def _container_name(container: Any) -> str:
    name = getattr(container, "name", None) or getattr(container, "short_id", None)
    if not name:
        raise SwesmithRuntimeError("SWE-smith container did not expose a name")
    return str(name)


def _repo_path(profile: Any) -> str:
    path = getattr(profile, "repo_path", None)
    if path:
        return str(path)
    return "/testbed"


def create_official_container(
    instance: dict[str, Any],
    *,
    reference_path: str | Path | None,
) -> SwesmithPreparedContainer:
    try:
        import_swesmith(reference_path=reference_path)
        profiles_module = importlib.import_module("swesmith.profiles")
        profile = profiles_module.registry.get_from_inst(instance)
        container = profile.get_container(instance)
    except Exception as exc:
        raise SwesmithRuntimeError(f"failed to create SWE-smith container for {instance.get('instance_id')}: {exc}") from exc
    return SwesmithPreparedContainer(
        instance_id=str(instance["instance_id"]),
        container_name=_container_name(container),
        repo_path=_repo_path(profile),
        profile_key=str(instance.get("repo") or str(instance["instance_id"]).rsplit(".", 1)[0]),
        raw_container=container,
        raw_profile=profile,
    )
