import json
from pathlib import Path

from coding_agent.models import Prediction
from coding_agent.sandbox.docker_cli import DockerResult
from coding_agent.swebench.prediction import export_prepared_environment_patch, prediction_to_dict, write_prediction_jsonl


def test_prediction_schema_uses_official_swebench_fields():
    prediction = Prediction("instance-1", "model-a", "diff --git a/file b/file\n")

    assert prediction_to_dict(prediction) == {
        "instance_id": "instance-1",
        "model_name_or_path": "model-a",
        "model_patch": "diff --git a/file b/file\n",
    }


def test_write_prediction_jsonl_writes_one_object_per_line(tmp_path: Path):
    output = tmp_path / "prediction.jsonl"
    prediction = Prediction("instance-1", "model-a", "patch")

    write_prediction_jsonl(output, prediction)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows == [prediction_to_dict(prediction)]


def test_export_prepared_environment_patch_uses_prepared_repo_path():
    class FakeDocker:
        def __init__(self) -> None:
            self.calls = []

        def exec(self, container, command):
            self.calls.append((container, command))
            return DockerResult("diff --git a/app.py b/app.py\n", "", 0)

    docker = FakeDocker()

    patch = export_prepared_environment_patch(docker, container_name="task-container", repo_path="/testbed")

    assert patch.startswith("diff --git")
    assert docker.calls == [("task-container", ["git", "-C", "/testbed", "diff", "--binary"])]
