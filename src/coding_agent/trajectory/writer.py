from __future__ import annotations

import json
import os
from pathlib import Path

from coding_agent.models import TrajectoryStep


class TrajectoryWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_step(self, step: TrajectoryStep) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(step.to_dict(), ensure_ascii=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

