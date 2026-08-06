from __future__ import annotations

from typing import Any

from coding_agent.models import ToolName

# Tool schema registry - single source of truth for tool definitions
TOOL_SCHEMAS: dict[ToolName, dict[str, Any]] = {
    ToolName.READ_FILE: {
        "description": """\
Read a UTF-8 text file or list a directory. Output is formatted with line
numbers (cat -n style). Shows the first 300 lines by default. Use view_range
to zoom into specific lines. If file_path is a directory, lists non-hidden
files and subdirectories up to 2 levels deep.""",
        "parameters": {
            "file_path": {
                "type": "string",
                "required": True,
                "description": "Absolute path to the file or directory.",
            },
            "view_range": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
                "description": "Show lines from START to END. Use -1 for END to read to end of file. Example: [400, 500] shows lines 400-500.",
            },
        },
        "examples": [
            '{"file_path": "src/main.py"}',
            '{"file_path": "src/main.py", "view_range": [400, 500]}',
            '{"file_path": "tests/"}',
        ],
    },
    ToolName.APPLY_PATCH: {
        "description": """\
Modify or create files. To update an existing file, set old_string to the
exact text to replace (copy it from read_file output to ensure exact
whitespace match) and new_string to the replacement. old_string must be
unique in the file — include enough surrounding context lines to make it
unique. To create a new file or overwrite an existing one, omit old_string
or set it to empty, and set new_string to the full file content.""",
        "parameters": {
            "path": {
                "type": "string",
                "required": True,
                "description": "Absolute path to the file.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to replace. Copy from read_file output for exact whitespace. Must be unique in the file. Omit or leave empty to create/overwrite the file.",
            },
            "new_string": {
                "type": "string",
                "required": True,
                "description": "Replacement text. If old_string is empty, this is the full file content.",
            },
        },
        "examples": [
            '{"path": "/testbed/src/main.py", "old_string": "    return b - a", "new_string": "    return a - b"}',
            '{"path": "/testbed/tests/test_new.py", "new_string": "import pytest\\n\\ndef test_foo():\\n    pass\\n"}',
        ],
    },
    ToolName.SEARCH: {
        "description": """\
Search repository text and repo-relative paths with a regular expression.
Use this for both content search and filename/path search. Results are
annotated with match_type="path" for path matches and match_type="content"
for line-content matches. Use glob to filter by file pattern.""",
        "parameters": {
            "pattern": {
                "type": "string",
                "required": True,
                "description": "Python regular expression for line content or filename/path search.",
            },
            "glob": {
                "type": "string",
                "description": 'Glob pattern to filter files (e.g. "**/*.py"). Defaults to all text files.',
            },
            "head_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "Maximum matches to return (default 250).",
            },
        },
        "examples": [
            '{"pattern": "^def calculate\\\\("}',
            '{"pattern": "class.*View", "glob": "**/*.py", "head_limit": 50}',
            '{"pattern": "graphics\\\\.py$"}',
            '{"pattern": "TODO", "glob": "**/*.py"}',
        ],
    },
    ToolName.EXECUTE_BASH: {
        "description": """\
Use execute_bash only for python scripts, pytest, pip install, and
project-specific test or lint commands. Chain multiple commands with && or ;.
A 30-second timeout applies. Note: some tools exit non-zero on success; if
stdout has output, the command succeeded.

Do not use execute_bash for reading files, listing many files, searching code,
or inspecting git history/status. Do not use shell redirection except 2>&1 or
stderr suppression to /dev/null. Do not use heredocs, command substitution, cat,
grep, find, awk, sed, or git. Pipes are allowed only for output clipping: pipe
only to head or tail. Use read_file for file/directory inspection and search
for text search plus filename/path search.""",
        "parameters": {
            "command": {
                "type": "string",
                "required": True,
                "description": "The bash command to execute. Do not use redirection except 2>&1 or stderr suppression to /dev/null. Do not use cat, grep, find, or git. You may pipe only to head or tail for output clipping. Examples: 'python reproduce_issue.py', 'python -m pytest test/foo.py -x --tb=short', 'python -m pytest tests -q 2>&1 | tail -50', 'pip install requests'.",
            },
        },
        "examples": [
            '{"command": "python reproduce_issue.py"}',
            '{"command": "python -m pytest test/foo.py::test_bar -x --tb=short"}',
            '{"command": "python -m pytest tests -q 2>&1 | tail -50"}',
            '{"command": "pip install requests"}',
        ],
    },
    ToolName.FINISH: {
        "description": "Signal that the task is complete and submit your solution. Call this when you have made all necessary changes and verified they work. Optionally include a brief summary of what was changed.",
        "parameters": {
            "result": {
                "type": "string",
                "description": "Optional. A brief summary of the changes made and why the task is resolved.",
            },
        },
        "examples": [
            '{"result": "Fixed the off-by-one error in src/calculator.py line 42"}',
            "{}",
        ],
    },
}
