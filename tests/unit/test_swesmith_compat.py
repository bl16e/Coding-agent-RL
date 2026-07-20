import sys

from coding_agent.swesmith.compat import install_windows_resource_shim


def test_install_windows_resource_shim_registers_minimal_module(monkeypatch):
    monkeypatch.setattr("coding_agent.swesmith.compat.os.name", "nt")
    monkeypatch.delitem(sys.modules, "resource", raising=False)

    install_windows_resource_shim()

    assert sys.modules["resource"].RLIMIT_NOFILE == 0
    sys.modules["resource"].setrlimit(0, (1, 1))
