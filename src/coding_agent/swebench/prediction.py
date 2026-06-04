from __future__ import annotations

import json
from pathlib import Path

from coding_agent.models import Prediction


def prediction_to_dict(prediction: Prediction) -> dict[str, str]:
    return {
        "instance_id": prediction.instance_id,
        "model_name_or_path": prediction.model_name_or_path,
        "model_patch": prediction.model_patch,
    }


def write_prediction_jsonl(path: str | Path, prediction: Prediction) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(prediction_to_dict(prediction), ensure_ascii=True) + "\n")

