from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from coding_agent.models import RunBudget


def validate_budget(budget: RunBudget) -> RunBudget:
    """重新构造预算对象，复用 RunBudget 的正整数校验。"""
    return RunBudget(
        max_steps=budget.max_steps,
        timeout_seconds=budget.timeout_seconds,
        test_timeout_seconds=budget.test_timeout_seconds,
    )


@dataclass(frozen=True)
class Deadline:
    """基于开始时间和超时秒数计算剩余时间。"""

    started_at: datetime
    timeout_seconds: int

    def remaining_seconds(self, now: datetime | None = None) -> float:
        """返回非负剩余秒数。"""
        current = now or datetime.now(timezone.utc)
        remaining = self.timeout_seconds - (current - self.started_at).total_seconds()
        return max(0.0, remaining)

    def expired(self, now: datetime | None = None) -> bool:
        """判断总运行预算是否已经耗尽。"""
        return self.remaining_seconds(now) <= 0


class BudgetTracker:
    """跟踪模型决策步数和总运行时间。

    测试命令超时由工具层使用 budget.test_timeout_seconds 控制；这里负责 agent loop
    级别的 max_steps 和 total timeout。
    """

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
        """消耗一次模型决策预算，并返回当前步数。"""
        if self.max_steps_reached:
            raise RuntimeError("max steps budget is exhausted")
        self.step_count += 1
        return self.step_count

    def total_timeout_reached(self, now: datetime | None = None) -> bool:
        """检查整次运行是否已超过总时间预算。"""
        return self.deadline.expired(now)
