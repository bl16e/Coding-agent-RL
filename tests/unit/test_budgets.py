from datetime import datetime, timedelta, timezone

import pytest

# REMOVED: budgets.py deleted BudgetTracker, Deadline, validate_budget
from coding_agent.models import RunBudget


def test_run_budget_requires_positive_values():
    with pytest.raises(ValueError, match="max_steps"):
        RunBudget(max_steps=0, timeout_seconds=60, test_timeout_seconds=10)

    with pytest.raises(ValueError, match="timeout_seconds"):
        validate_budget(RunBudget(max_steps=1, timeout_seconds=-1, test_timeout_seconds=10))


def test_deadline_reports_remaining_time_and_expiry():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = Deadline(started_at=started, timeout_seconds=10)

    assert deadline.remaining_seconds(started + timedelta(seconds=3)) == pytest.approx(7)
    assert not deadline.expired(started + timedelta(seconds=9.9))
    assert deadline.expired(started + timedelta(seconds=10))


def test_budget_tracker_consumes_steps_until_exhausted():
    tracker = BudgetTracker(RunBudget(max_steps=2, timeout_seconds=60, test_timeout_seconds=5))

    assert tracker.consume_step() == 1
    assert tracker.consume_step() == 2
    assert tracker.max_steps_reached
    with pytest.raises(RuntimeError, match="max steps"):
        tracker.consume_step()

