from coding_agent.agent import _ToolAction, _detect_conflicts
from coding_agent.models import ToolName


def test_all_non_conflicting_grouped_together():
    actions = [
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "a.py"}),
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "b.py"}),
        _ToolAction(tool_name=ToolName.SEARCH, tool_input={"pattern": "x"}),
    ]
    groups = _detect_conflicts(actions)
    assert sorted(sum(groups, [])) == [0, 1, 2]
    assert len(groups[0]) == 3


def test_single_action_one_group():
    actions = [
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "a.py"}),
    ]
    groups = _detect_conflicts(actions)
    assert groups == [[0]]


def test_write_same_file_conflicts():
    """Two APPLY_PATCH to same path — serialized."""
    actions = [
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={"path": "a.py", "old_string": "old", "new_string": "x"}),
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={"path": "a.py", "old_string": "other", "new_string": "y"}),
    ]
    groups = _detect_conflicts(actions)
    assert len(groups) == 2


def test_write_different_files_parallel():
    """Two APPLY_PATCH to different paths — parallel."""
    actions = [
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={"path": "a.py", "old_string": "old", "new_string": "x"}),
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={"path": "b.py", "old_string": "old", "new_string": "y"}),
    ]
    groups = _detect_conflicts(actions)
    assert len(groups) == 1


def test_read_write_same_file_conflicts():
    actions = [
        _ToolAction(tool_name=ToolName.READ_FILE, tool_input={"file_path": "a.py"}),
        _ToolAction(tool_name=ToolName.APPLY_PATCH, tool_input={"path": "a.py", "old_string": "old", "new_string": "new"}),
    ]
    groups = _detect_conflicts(actions)
    assert [0] in groups or len(groups) > 1
