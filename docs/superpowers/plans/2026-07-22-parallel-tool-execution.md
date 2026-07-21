# Parallel Tool Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the agent loop from serial to model-driven parallel tool execution — multiple tool_calls in one model response are executed concurrently via ThreadPoolExecutor.

**Architecture:** `ModelBackend.next_action()` returns `list[AgentAction]` instead of a single `AgentAction`. The agent loop dispatches all non-FINAL actions to a thread pool, detects file conflicts (same file_path with a write) and serializes those, then collects results. One model response = 1 step regardless of tool count.

**Tech Stack:** Python 3.12, `concurrent.futures.ThreadPoolExecutor`, existing `coding_agent` tool infrastructure.

## Global Constraints

- All existing unit tests must keep passing
- `FINAL` action must appear alone (not mixed with tool calls)
- Single-tool responses behave identically to before
- Path: source changes in `src/coding_agent/`, tests in `tests/`

---

### Task 1: Update ModelBackend interface — return list[AgentAction]

**Files:**
- Modify: `src/coding_agent/model_backends/base.py:33-36`

**Interfaces:**
- Produces: `ModelBackend.next_action(messages) -> list[AgentAction]`

- [ ] **Step 1: Change the Protocol return type**

```python
# src/coding_agent/model_backends/base.py, line 33-36
class ModelBackend(Protocol):
    def next_action(self, messages: list[dict[str, Any]]) -> list[AgentAction]:
        ...
```

Change the return type annotation from `AgentAction` to `list[AgentAction]`.

- [ ] **Step 2: Verify no other source files import the old single-return type**

Run: `python -c "from coding_agent.model_backends.base import ModelBackend; print('ok')"`
Expected: "ok" (no import errors)

- [ ] **Step 3: Commit**

```bash
git add src/coding_agent/model_backends/base.py
git commit -m "refactor: ModelBackend.next_action returns list[AgentAction]"
```

---

### Task 2: Update OpenAI-compatible backend — parse all tool_calls

**Files:**
- Modify: `src/coding_agent/model_backends/openai_compatible.py:194-222`

**Interfaces:**
- Consumes: `list[AgentAction]` from Task 1
- Produces: `_parse_tool_calls_message(message) -> list[AgentAction]`; `parse_agent_action(payload) -> list[AgentAction]`

- [ ] **Step 1: Rewrite `_parse_tool_call_message` to `_parse_tool_calls_message` returning a list**

```python
# src/coding_agent/model_backends/openai_compatible.py, replace lines 194-222

def _parse_tool_calls_message(message: dict[str, Any]) -> list[AgentAction]:
    """Parse all tool_calls from an OpenAI-compatible assistant message."""
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return []
    actions: list[AgentAction] = []
    for tool_call in tool_calls:
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        name = function.get("name")
        arguments_text = function.get("arguments") or "{}"
        try:
            arguments = json.loads(arguments_text)
        except json.JSONDecodeError as exc:
            raise ModelBackendError(f"tool call arguments are not valid JSON for {name}") from exc
        if not isinstance(arguments, dict):
            raise ModelBackendError(f"tool call arguments must be a JSON object for {name}")
        try:
            action_type = AgentActionType(name)
        except ValueError as exc:
            raise ModelBackendError(f"Unsupported agent action: {name}") from exc
        actions.append(AgentAction(
            action=action_type,
            tool_input={} if action_type is AgentActionType.FINAL else arguments,
            reasoning_summary=arguments.get("reasoning_summary") or "",
            next_intent=arguments.get("next_intent") or "",
            tool_selection_reason=arguments.get("tool_selection_reason") or "",
            final_status=arguments.get("final_status") if action_type is AgentActionType.FINAL else None,
            final_message=arguments.get("final_message") if action_type is AgentActionType.FINAL else None,
            tool_call_id=tool_call.get("id"),
            raw_message=message,
        ))
    return actions
```

- [ ] **Step 2: Update `_payload_to_action_dict` to use the new function**

```python
# In _payload_to_action_dict, line 248-250, change:
        tool_action = _parse_tool_call_message(message)
        if tool_action is not None:
            return {"__agent_action__": tool_action}
# to:
        tool_actions = _parse_tool_calls_message(message)
        if tool_actions:
            return {"__agent_actions__": tool_actions}
```

Rename `__agent_action__` key to `__agent_actions__`.

- [ ] **Step 3: Update `parse_agent_action` to return list and handle the new key**

```python
# src/coding_agent/model_backends/openai_compatible.py, replace lines 257-276

def parse_agent_action(payload: dict[str, Any] | str) -> list[AgentAction]:
    """Validate provider output and convert it into executable actions."""

    action_dict = _payload_to_action_dict(payload)
    if "__agent_actions__" in action_dict:
        return action_dict["__agent_actions__"]
    # JSON text mode: single action (legacy path)
    action_value = action_dict.get("action")
    try:
        action = AgentActionType(action_value)
    except ValueError as exc:
        raise ModelBackendError(f"Unsupported agent action: {action_value}") from exc
    return [AgentAction(
        action=action,
        tool_input=action_dict.get("tool_input") or {},
        reasoning_summary=action_dict.get("reasoning_summary") or "",
        next_intent=action_dict.get("next_intent") or "",
        tool_selection_reason=action_dict.get("tool_selection_reason") or "",
        final_status=action_dict.get("final_status"),
        final_message=action_dict.get("final_message"),
    )]
```

- [ ] **Step 4: Update `OpenAICompatibleBackend.next_action` return type**

```python
# Line 312: change return type annotation
    def next_action(self, messages: list[dict[str, Any]]) -> list[AgentAction]:
```

- [ ] **Step 5: Run existing backend tests**

Run: `pytest tests/unit/test_openai_compatible_backend.py -v --basetemp=E:/Document/coding_agent/.tmp/pytest`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/coding_agent/model_backends/openai_compatible.py
git commit -m "feat: parse all tool_calls from OpenAI-compatible responses"
```

---

### Task 3: Update MockBackend to return list[AgentAction]

**Files:**
- Modify: `src/coding_agent/model_backends/mock.py`

**Interfaces:**
- Consumes: `list[AgentAction]` from Task 1
- Produces: `MockBackend.next_action(messages) -> list[AgentAction]`

- [ ] **Step 1: Change return type to list**

```python
# src/coding_agent/model_backends/mock.py

class MockBackend:
    def __init__(self, actions: Iterable[AgentAction] | None = None) -> None:
        self._actions = list(actions or [])
        self._index = 0

    def next_action(self, messages: list[dict[str, str]]) -> list[AgentAction]:
        if self._index >= len(self._actions):
            return [AgentAction(
                action=AgentActionType.FINAL,
                reasoning_summary="No mock actions remain",
                next_intent="Stop run",
                final_status="incomplete",
                final_message="Mock backend exhausted",
            )]
        action = self._actions[self._index]
        self._index += 1
        return [action]
```

- [ ] **Step 2: Run test to verify**

Run: `python -c "from coding_agent.model_backends.mock import MockBackend; mb = MockBackend(); acts = mb.next_action([]); print(type(acts), len(acts))"`
Expected: `<class 'list'> 1`

- [ ] **Step 3: Commit**

```bash
git add src/coding_agent/model_backends/mock.py
git commit -m "refactor: MockBackend.next_action returns list[AgentAction]"
```

---

### Task 4: Add conflict detection and parallel execution to agent loop

**Files:**
- Modify: `src/coding_agent/agent.py`

**Interfaces:**
- Consumes: `list[AgentAction]` from backend; `ToolExecutor.execute()` unchanged
- Produces: `_parallel_execute(executor, actions) -> list[ToolExecutionResult]`; `_detect_conflicts(actions) -> list[list[int]]`

- [ ] **Step 1: Add imports**

```python
# Add at top of agent.py
from concurrent.futures import ThreadPoolExecutor, as_completed
```

- [ ] **Step 2: Add conflict detection function**

```python
# Add before run_task()

def _detect_conflicts(actions: list[AgentAction]) -> list[list[int]]:
    """Group action indices that conflict on the same file_path.

    Two actions conflict when they target the same file and at least one
    is a write (APPLY_PATCH).  Conflicting groups must run serially;
    non-conflicting actions run in parallel.

    Returns a list of groups, each group being a list of indices into *actions*.
    """
    # Build file_path -> list of indices for write operations
    write_targets: dict[str, list[int]] = {}
    for i, action in enumerate(actions):
        if action.action is AgentActionType.APPLY_PATCH:
            fp = action.tool_input.get("file_path", "")
            if fp:
                write_targets.setdefault(fp, []).append(i)

    # Build file_path -> list of indices for read operations
    read_targets: dict[str, list[int]] = {}
    for i, action in enumerate(actions):
        if action.action is AgentActionType.READ_FILE:
            fp = action.tool_input.get("file_path", "")
            if fp and fp in write_targets:
                read_targets.setdefault(fp, []).append(i)

    # Collect conflicting indices
    conflicting: set[int] = set()
    for fp, indices in write_targets.items():
        if len(indices) > 1:
            conflicting.update(indices)  # multiple writes to same file
        conflicting.update(read_targets.get(fp, []))  # read + write to same file

    if not conflicting:
        # All actions can run in parallel
        return [[i] for i in range(len(actions))]

    # Build groups: conflicting indices each get their own group (serial),
    # non-conflicting indices all go in one parallel group
    parallel_group = [i for i in range(len(actions)) if i not in conflicting]
    groups: list[list[int]] = []
    if parallel_group:
        groups.append(parallel_group)
    for i in sorted(conflicting):
        groups.append([i])
    return groups
```

- [ ] **Step 3: Add parallel execution function**

```python
# Add after _detect_conflicts()

def _parallel_execute(
    executor: ToolExecutor,
    actions: list[AgentAction],
    action_tool_map: dict[AgentActionType, ToolName],
) -> list[ToolExecutionResult]:
    """Execute *actions* with concurrency where safe.

    Non-conflicting actions run in a ThreadPoolExecutor.  Conflicting
    actions (same file_path with a write) run sequentially.
    """
    if len(actions) == 1:
        tool_name = action_tool_map[actions[0].action]
        return [executor.execute(tool_name, actions[0].tool_input)]

    groups = _detect_conflicts(actions)
    results: list[ToolExecutionResult] = [None] * len(actions)  # type: ignore

    for group in groups:
        if len(group) == 1:
            # Single action — execute directly
            idx = group[0]
            tool_name = action_tool_map[actions[idx].action]
            results[idx] = executor.execute(tool_name, actions[idx].tool_input)
        else:
            # Multiple non-conflicting actions — run in parallel
            def _run_one(idx: int) -> tuple[int, ToolExecutionResult]:
                tn = action_tool_map[actions[idx].action]
                return idx, executor.execute(tn, actions[idx].tool_input)

            with ThreadPoolExecutor(max_workers=len(group)) as pool:
                futures = {pool.submit(_run_one, i): i for i in group}
                for future in as_completed(futures):
                    idx, result = future.result()
                    results[idx] = result

    return results
```

- [ ] **Step 4: Rewrite the agent main loop to process batches**

Replace lines 359-406 (the main while loop body) in `agent.py`:

```python
    while not tracker.max_steps_reached:
        if tracker.total_timeout_reached():
            final_error = "total runtime budget reached"
            break
        tracker.consume_step()
        actions = backend.next_action([dict(message) for message in messages])

        # --- Record model decision ---
        try:
            writer.write_step(_decision_step(trajectory_index, actions[0]))
        except OSError as exc:
            raise ArtifactPersistenceError(str(exc)) from exc
        trajectory_index += 1

        # --- Append model messages to history ---
        for action in actions:
            messages.append(_action_message(action))

        # --- Check for FINAL ---
        if any(a.action is AgentActionType.FINAL for a in actions):
            final_action = next(a for a in actions if a.action is AgentActionType.FINAL)
            terminal_status = _terminal_status(final_action)
            if terminal_status is RunStatus.SOLVED and unresolved_tool_failure:
                agent_run.finish(RunStatus.INCOMPLETE)
                final_error = "model reported solved after unresolved tool failure"
            else:
                agent_run.finish(terminal_status)
                final_error = final_action.final_message
            break

        # --- Filter to tool actions only ---
        tool_actions = [a for a in actions if a.action is not AgentActionType.FINAL]

        # --- Execute in parallel ---
        results = _parallel_execute(executor, tool_actions, ACTION_TOOL_MAP)
        for action, result in zip(tool_actions, results):
            if result.status is Outcome.OK:
                last_successful_tool_call = result.tool_name.value
            else:
                unresolved_tool_failure = True
            for modification in result.modifications:
                if result.status is Outcome.OK and _is_test_path(modification.path):
                    authored_test_identifiers.update(_test_path_identifiers(modification.path))
            if result.test_result is not None:
                key = result.test_result.status.value
                test_summary[key] = test_summary.get(key, 0) + 1
                category = _self_test_category(result.test_result.command, authored_test_identifiers)
                self_test_coverage[category][key] = self_test_coverage[category].get(key, 0) + 1
                if key == "passed":
                    unresolved_tool_failure = False
            try:
                writer.write_step(_tool_result_step(trajectory_index, result, action.tool_input))
            except OSError as exc:
                raise ArtifactPersistenceError(str(exc)) from exc
            trajectory_index += 1
            messages.append(_tool_history_message(action, result))
```

- [ ] **Step 5: Commit**

```bash
git add src/coding_agent/agent.py
git commit -m "feat: parallel tool execution with conflict detection"
```

---

### Task 5: Update all tests — adapt mock backends to return lists

**Files:**
- Modify: `tests/unit/test_agent_run_lifecycle.py`
- Modify: `tests/unit/test_trajectory_content.py`
- Modify: `tests/integration/test_tool_constraints.py`
- Modify: `tests/unit/test_openai_compatible_backend.py`

**Interfaces:**
- Consumes: `next_action` returns `list[AgentAction]`
- Produces: Updated test assertions

- [ ] **Step 1: Update test mock backends in `test_agent_run_lifecycle.py`**

All `MockBackend`, `TwoStepCapturingBackend`, `NativeToolCallCapturingBackend`, `ReadValidatorsBackend`, etc. — change `self.messages_by_call.append(messages)` pattern to handle list return. The backends themselves already work (they return AgentAction which gets wrapped in a list by MockBackend). Only the `ScriptedExecutor`-based tests might need adjustment.

- [ ] **Step 2: Run all unit tests**

Run: `pytest tests/unit/ -v --basetemp=E:/Document/coding_agent/.tmp/pytest`
Expected: All pass

- [ ] **Step 3: Fix any failures iteratively**

For each failing test, update mock backends or assertions to handle `list[AgentAction]`.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test: adapt tests for list[AgentAction] return from backends"
```

---

### Task 6: Add parallel execution tests

**Files:**
- Create: `tests/unit/test_parallel_execution.py`

- [ ] **Step 1: Write conflict detection tests**

```python
from coding_agent.agent import _detect_conflicts
from coding_agent.model_backends.base import AgentAction, AgentActionType


def test_no_conflicts_when_different_files():
    actions = [
        AgentAction(action=AgentActionType.READ_FILE, tool_input={"file_path": "a.py"}),
        AgentAction(action=AgentActionType.READ_FILE, tool_input={"file_path": "b.py"}),
        AgentAction(action=AgentActionType.SEARCH_CODE, tool_input={"pattern": "x"}),
    ]
    groups = _detect_conflicts(actions)
    # All non-conflicting: one group with all indices
    assert sorted(sum(groups, [])) == [0, 1, 2]
    assert len(groups[0]) == 3


def test_conflict_read_write_same_file():
    actions = [
        AgentAction(action=AgentActionType.READ_FILE, tool_input={"file_path": "a.py"}),
        AgentAction(action=AgentActionType.APPLY_PATCH, tool_input={"type": "write", "file_path": "a.py", "content": "x"}),
        AgentAction(action=AgentActionType.READ_FILE, tool_input={"file_path": "b.py"}),
    ]
    groups = _detect_conflicts(actions)
    # a.py: indices 0 and 1 conflict → each gets own group
    # b.py: index 2 → parallel group
    # Groups: [parallel], [write a], [read a]  or similar
    flat = sum(groups, [])
    assert 2 in flat  # b.py is somewhere


def test_conflict_two_writes_same_file():
    actions = [
        AgentAction(action=AgentActionType.APPLY_PATCH, tool_input={"type": "write", "file_path": "a.py", "content": "x"}),
        AgentAction(action=AgentActionType.APPLY_PATCH, tool_input={"type": "write", "file_path": "a.py", "content": "y"}),
    ]
    groups = _detect_conflicts(actions)
    # Both write to a.py → both in their own serial groups
    assert len(groups) == 2


def test_single_action_no_conflict():
    actions = [
        AgentAction(action=AgentActionType.READ_FILE, tool_input={"file_path": "a.py"}),
    ]
    groups = _detect_conflicts(actions)
    assert groups == [[0]]
```

- [ ] **Step 2: Run conflict detection tests**

Run: `pytest tests/unit/test_parallel_execution.py -v --basetemp=E:/Document/coding_agent/.tmp/pytest`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_parallel_execution.py
git commit -m "test: add conflict detection unit tests"
```

---

### Task 7: Final integration verification

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/unit/ tests/integration/ -v --basetemp=E:/Document/coding_agent/.tmp/pytest`
Expected: All pass

- [ ] **Step 2: Run contract tests**

Run: `pytest tests/contract/ -v --basetemp=E:/Document/coding_agent/.tmp/pytest`
Expected: All pass or pre-existing failures only

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final integration verification for parallel execution"
```
