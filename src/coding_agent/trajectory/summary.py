from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coding_agent.models import RunSummary


def write_summary(path: str | Path, summary: RunSummary) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")


def load_summary(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

