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
