from __future__ import annotations

import json
from pathlib import Path

from coding_agent.models import Prediction


def prediction_to_dict(prediction: Prediction) -> dict[str, str]:
    """Return the official SWE-Bench prediction JSONL field set."""

    return {
        "instance_id": prediction.instance_id,
        "model_name_or_path": prediction.model_name_or_path,
        "model_patch": prediction.model_patch,
    }


def write_prediction_jsonl(path: str | Path, prediction: Prediction) -> None:
    """Write one prediction record, matching one task attempt per run."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(prediction_to_dict(prediction), ensure_ascii=True) + "\n")


def export_prediction_from_run(run_dir: str | Path, model_name: str, output: str | Path) -> None:
    """Rebuild a prediction JSONL from persisted run artifacts.

    This command path lets users change the reported model name without rerunning
    the agent, while the patch itself remains the exact final.patch artifact.
    """

    run_path = Path(run_dir)
    summary_path = run_path / "summary.json"
    patch_path = run_path / "final.patch"
    if not summary_path.is_file():
        raise FileNotFoundError("summary.json is required")
    if not patch_path.is_file():
        raise FileNotFoundError("final.patch is required")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    prediction = Prediction(summary["instance_id"], model_name, patch_path.read_text(encoding="utf-8"))
    write_prediction_jsonl(output, prediction)
