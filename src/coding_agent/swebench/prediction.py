from __future__ import annotations

import json
from pathlib import Path

from coding_agent.models import Prediction


def prediction_to_dict(prediction: Prediction) -> dict[str, str]:
    """返回官方 SWE-Bench prediction JSONL 字段集合。

    字段名必须保持 instance_id/model_name_or_path/model_patch，方便直接提交给
    SWE-Bench harness 或后续评估脚本。
    """

    return {
        "instance_id": prediction.instance_id,
        "model_name_or_path": prediction.model_name_or_path,
        "model_patch": prediction.model_patch,
    }


def write_prediction_jsonl(path: str | Path, prediction: Prediction) -> None:
    """写入单行 prediction。

    当前项目一次只运行一个任务，所以 prediction.jsonl 只包含一条记录。
    """

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(prediction_to_dict(prediction), ensure_ascii=True) + "\n")


def write_predictions_jsonl(path: str | Path, predictions: list[Prediction] | tuple[Prediction, ...]) -> None:
    """Write multiple SWE-Bench prediction records in JSONL order."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for prediction in predictions:
            handle.write(json.dumps(prediction_to_dict(prediction), ensure_ascii=True) + "\n")


def export_prediction_from_run(run_dir: str | Path, model_name: str, output: str | Path) -> None:
    """从已有运行产物重建 prediction JSONL。

    这个命令允许用户在不重跑 agent 的情况下更换上报模型名；patch 内容仍然严格来自
    final.patch，避免导出阶段引入新的代码差异。
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
