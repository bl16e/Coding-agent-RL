from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from coding_agent.models import RunBudget


def validate_budget(budget: RunBudget) -> RunBudget:
    return RunBudget(
        max_steps=budget.max_steps,
        timeout_seconds=budget.timeout_seconds,
        test_timeout_seconds=budget.test_timeout_seconds,
    )


@dataclass(frozen=True)
class Deadline:
    started_at: datetime
    timeout_seconds: int

    def remaining_seconds(self, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        remaining = self.timeout_seconds - (current - self.started_at).total_seconds()
        return max(0.0, remaining)

    def expired(self, now: datetime | None = None) -> bool:
        return self.remaining_seconds(now) <= 0


class BudgetTracker:
    def __init__(self, budget: RunBudget, started_at: datetime | None = None) -> None:
        self.budget = validate_budget(budget)
        self.deadline = Deadline(started_at or datetime.now(timezone.utc), self.budget.timeout_seconds)
        self.step_count = 0

    @property
    def max_steps_reached(self) -> bool:
        return self.step_count >= self.budget.max_steps

    @property
    def test_timeout_seconds(self) -> int:
        return self.budget.test_timeout_seconds

    def consume_step(self) -> int:
        if self.max_steps_reached:
            raise RuntimeError("max steps budget is exhausted")
        self.step_count += 1
        return self.step_count

    def total_timeout_reached(self, now: datetime | None = None) -> bool:
        return self.deadline.expired(now)

