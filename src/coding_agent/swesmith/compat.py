from __future__ import annotations

import os
import sys
import types


def install_windows_resource_shim() -> None:
    """Provide the Unix-only resource module symbols SWE-bench imports on Windows."""
    if os.name != "nt" or "resource" in sys.modules:
        return
    module = types.ModuleType("resource")
    module.RLIMIT_NOFILE = 0
    module.setrlimit = lambda *args, **kwargs: None
    sys.modules["resource"] = module


def windows_resource_shim_prelude() -> str:
    return (
        "import os, sys, types; "
        "m=types.ModuleType('resource'); "
        "m.RLIMIT_NOFILE=0; "
        "m.setrlimit=lambda *a, **k: None; "
        "sys.modules.setdefault('resource', m); "
    )


def windows_official_eval_prelude() -> str:
    patch_code = """
import io
import posixpath
import tarfile

def _ca_copy_to_container(container, src, dst):
    dst_text = str(dst).replace("\\\\", "/")
    parent = posixpath.dirname(dst_text)
    name = posixpath.basename(dst_text)
    tar_path = src.with_suffix(".tar")
    with tarfile.open(tar_path, "w") as tar:
        if name.endswith(".sh"):
            payload = src.read_text().replace("\\r\\n", "\\n").replace("\\r", "\\n").encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        else:
            tar.add(src, arcname=name)
    with open(tar_path, "rb") as tar_file:
        data = tar_file.read()
    container.exec_run(["mkdir", "-p", parent])
    container.put_archive(parent, data)
    tar_path.unlink()

import swebench.harness.docker_utils as _ca_du
_ca_du.copy_to_container = _ca_copy_to_container
import swesmith.harness.utils as _ca_su
_ca_su.copy_to_container = _ca_copy_to_container
"""
    return windows_resource_shim_prelude() + f"exec({patch_code!r}); "
