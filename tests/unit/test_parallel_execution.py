from coding_agent.agent import _ToolAction, _detect_conflicts
from coding_agent.models import ToolName


def test_all_non_conflicting_grouped_together():
    actions = [
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "a.py"}),
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "b.py"}),
        _ToolAction(tool_name=ToolName.SEARCH_CODE, tool_input={"pattern": "x"}),
    ]
    groups = _detect_conflicts(actions)
    # All in one parallel group
    assert sorted(sum(groups, [])) == [0, 1, 2]
    assert len(groups[0]) == 3


def test_single_action_one_group():
    actions = [
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "a.py"}),
    ]
    groups = _detect_conflicts(actions)
    assert groups == [[0]]


def test_read_write_same_file_conflicts():
    actions = [
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "a.py"}),
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={
            "type": "write", "file_path": "a.py", "content": "x",
        }),
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "b.py"}),
    ]
    groups = _detect_conflicts(actions)
    # a.py read (0) and write (1) conflict with each other.
    # b.py read (2) has no conflict but there are no other parallel actions.
    # So each gets its own single-action group.
    flat = sum(groups, [])
    assert set(flat) == {0, 1, 2}
    # 0 and 1 must be in their own groups (they conflict)
    assert [0] in groups
    assert [1] in groups


def test_two_writes_same_file_conflicts():
    actions = [
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={
            "type": "write", "file_path": "a.py", "content": "x",
        }),
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={
            "type": "write", "file_path": "a.py", "content": "y",
        }),
    ]
    groups = _detect_conflicts(actions)
    # Both write to a.py -> both in separate serial groups
    assert len(groups) == 2
    assert all(len(g) == 1 for g in groups)


def test_write_different_files_no_conflict():
    actions = [
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={
            "type": "write", "file_path": "a.py", "content": "x",
        }),
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={
            "type": "write", "file_path": "b.py", "content": "y",
        }),
    ]
    groups = _detect_conflicts(actions)
    # Different files -> no conflict -> single parallel group
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_update_read_same_file_conflicts():
    actions = [
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "a.py"}),
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={
            "type": "update", "file_path": "a.py",
            "old_string": "old", "new_string": "new",
        }),
    ]
    groups = _detect_conflicts(actions)
    # Update affects a.py -> conflict with Read on a.py
    assert len(groups) == 2
    assert all(len(g) == 1 for g in groups)
