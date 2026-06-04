import json
from datetime import datetime, timezone
from pathlib import Path

from coding_agent.models import Outcome, StepActionType, TrajectoryStep
from coding_agent.trajectory.writer import TrajectoryWriter


def test_trajectory_writer_preserves_order_and_flushes_each_step(tmp_path: Path):
    path = tmp_path / "trajectory.jsonl"
    writer = TrajectoryWriter(path)

    writer.write_step(
        TrajectoryStep(
            step_index=1,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            action_type=StepActionType.MODEL,
            outcome=Outcome.OK,
            reasoning_summary="Read the problem",
            next_intent="Inspect files",
        )
    )

    assert path.read_text(encoding="utf-8").count("\n") == 1

    writer.write_step(
        TrajectoryStep(
            step_index=2,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            action_type=StepActionType.FINAL,
            outcome=Outcome.OK,
        )
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["step_index"] for row in rows] == [1, 2]

