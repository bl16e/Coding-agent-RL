import json
from pathlib import Path

from coding_agent.cli import main


class FakeDockerCli:
    def image_exists(self, image: str) -> bool:
        return image == "django-base:latest"


def test_sandbox_register_requires_declared_arguments(capsys):
    exit_code = main(["sandbox", "register"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--repo" in captured.err
    assert "--image" in captured.err
    assert "--repo-path" in captured.err


def test_sandbox_register_saves_registry_entry(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("coding_agent.cli.DockerCli", FakeDockerCli)
    registry = tmp_path / "sandboxes.json"

    exit_code = main(
        [
            "sandbox",
            "register",
            "--repo",
            "django/django",
            "--image",
            "django-base:latest",
            "--repo-path",
            "/workspace/repo",
            "--registry",
            str(registry),
            "--official-compatible",
            "--compatibility-source",
            "official notes",
            "--validation-command-template",
            "python -m pytest {tests}",
        ]
    )

    data = json.loads(registry.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert data["sandboxes"]["django/django"]["official_compatible"] is True
    assert data["sandboxes"]["django/django"]["validation_command_template"] == "python -m pytest {tests}"


def test_sandbox_register_rejects_missing_docker_image(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("coding_agent.cli.DockerCli", FakeDockerCli)

    exit_code = main(
        [
            "sandbox",
            "register",
            "--repo",
            "django/django",
            "--image",
            "missing:latest",
            "--repo-path",
            "/workspace/repo",
            "--registry",
            str(tmp_path / "sandboxes.json"),
        ]
    )

    assert exit_code == 2
    assert "image not found" in capsys.readouterr().err


def test_sandbox_list_prints_registered_entries(tmp_path: Path, capsys):
    registry = tmp_path / "sandboxes.json"
    registry.write_text(
        json.dumps(
            {
                "sandboxes": {
                    "django/django": {
                        "repo": "django/django",
                        "image": "django-base:latest",
                        "repo_path": "/workspace/repo",
                        "official_compatible": True,
                        "validation_command_template": "python -m pytest {tests}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["sandbox", "list", "--registry", str(registry)])

    assert exit_code == 0
    assert "django/django" in capsys.readouterr().out
