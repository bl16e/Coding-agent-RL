import sys
import types
from pathlib import Path

import pytest

from coding_agent.swesmith.runtime import (
    SwesmithRuntimeError,
    create_official_container,
    import_swesmith,
)


def test_import_swesmith_adds_reference_path(tmp_path: Path, monkeypatch):
    package = tmp_path / "SWE-smith" / "swesmith"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    sys.modules.pop("swesmith", None)

    module = import_swesmith(reference_path=tmp_path / "SWE-smith")

    assert module.VALUE == 42


def test_import_swesmith_adds_local_swebench_checkout(tmp_path: Path, monkeypatch):
    swesmith_package = tmp_path / "Reference" / "SWE-smith" / "swesmith"
    swesmith_package.mkdir(parents=True)
    (swesmith_package / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    swebench_root = tmp_path / "SWE-bench"
    swebench_root.mkdir()
    sys.modules.pop("swesmith", None)

    import_swesmith(
        reference_path=tmp_path / "Reference" / "SWE-smith",
        swebench_path=swebench_root,
    )

    assert str(swebench_root.resolve()) in sys.path


def test_import_swesmith_reports_missing_checkout(tmp_path: Path):
    with pytest.raises(SwesmithRuntimeError, match="SWE-smith checkout does not exist"):
        import_swesmith(reference_path=tmp_path / "missing")


def test_create_official_container_uses_registry_get_from_inst(monkeypatch):
    calls = {}

    class FakeContainer:
        name = "swesmith.task.instance"

    class FakeProfile:
        repo_path = "/testbed"

        def get_container(self, instance):
            calls["instance"] = instance
            return FakeContainer()

    fake_registry = types.SimpleNamespace(get_from_inst=lambda instance: FakeProfile())
    fake_profiles = types.SimpleNamespace(registry=fake_registry)
    monkeypatch.setitem(sys.modules, "swesmith", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "swesmith.profiles", fake_profiles)

    prepared = create_official_container({"instance_id": "repo__name.pr_1"}, reference_path=None)

    assert prepared.container_name == "swesmith.task.instance"
    assert prepared.repo_path == "/testbed"
    assert calls["instance"]["instance_id"] == "repo__name.pr_1"


def test_create_official_container_wraps_profile_failure(monkeypatch):
    fake_registry = types.SimpleNamespace(get_from_inst=lambda instance: (_ for _ in ()).throw(KeyError("missing")))
    fake_profiles = types.SimpleNamespace(registry=fake_registry)
    monkeypatch.setitem(sys.modules, "swesmith", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "swesmith.profiles", fake_profiles)

    with pytest.raises(SwesmithRuntimeError, match="failed to create SWE-smith container"):
        create_official_container({"instance_id": "repo__name.pr_1"}, reference_path=None)
