from __future__ import annotations

import json
import os
from pathlib import Path

from coding_agent.models import TrajectoryStep


class TrajectoryWriter:
    """追加写 JSONL 的轨迹记录器。

    agent 的每次模型决策和工具结果都独立成行，便于在运行中断后读取最后一个完整事件。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def write_step(self, step: TrajectoryStep) -> None:
        """在 agent 继续执行前持久化一个轨迹步骤。

        这里刻意使用 fsync，虽然有少量性能成本，但完整恢复轨迹是核心需求；部分失败的
        运行也应当展示最后一次已接受的模型决策或工具结果。
        """

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(step.to_dict(), ensure_ascii=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
