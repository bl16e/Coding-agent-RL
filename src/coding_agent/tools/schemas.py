from __future__ import annotations

from typing import Any

from coding_agent.models import ToolName

# Common properties included in all tool calls for context tracking
COMMON_PROPERTIES = {
    "reasoning_summary": {
        "type": "string",
        "description": "Brief reason for this tool choice.",
    },
    "next_intent": {
        "type": "string",
        "description": "What you plan to do after this result.",
    },
    "tool_selection_reason": {
        "type": "string",
        "description": "Why this tool is appropriate now.",
    },
}

# Tool schema registry - single source of truth for tool definitions
TOOL_SCHEMAS: dict[ToolName, dict[str, Any]] = {
    ToolName.READ_FILE: {
        "description": "Read a UTF-8 text file from the repository. Output is formatted with line numbers (cat -n style). Use offset and limit for large files.",
        "parameters": {
            "file_path": {
                "type": "string",
                "required": True,
                "description": "Repository-relative file path.",
            },
            "offset": {
                "type": "integer",
                "minimum": 1,
                "description": "1-based start line number (default 1).",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Number of lines to read (default 200).",
            },
        },
        "examples": [
            '{"file_path": "src/main.py"}',
            '{"file_path": "README.md", "offset": 10, "limit": 50}',
            '{"file_path": "src/main.py", "offset": 100}',
        ],
    },
    ToolName.APPLY_PATCH: {
        "description": "Modify the repository by writing files or applying exact string replacements. Use write to create or overwrite a file. Use update to replace old_string with new_string via exact match (old_string must appear exactly once).",
        "parameters": {
            "type": {
                "type": "string",
                "required": True,
                "enum": ["write", "update"],
                "description": "Operation type: write (create or overwrite a file), update (exact string replacement).",
            },
            "file_path": {
                "type": "string",
                "description": "Repository-relative file path for write and update operations.",
            },
            "content": {
                "type": "string",
                "description": "Complete file content for write operation.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to replace for update operation. Must appear exactly once in the file. Include enough surrounding context (indentation, blank lines, neighbouring code) to make it unique.",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text for update operation.",
            },
        },
        "examples": [
            '{"type": "write", "file_path": "tests/test_calc.py", "content": "import pytest\\n..."}',
            '{"type": "update", "file_path": "src/main.py", "old_string": "def substract(a, b):", "new_string": "def subtract(a, b):"}',
        ],
    },
    ToolName.SEARCH_CODE: {
        "description": "Search repository text files with a regular expression. Returns matching lines with optional context. Use glob to filter by file pattern (e.g. \"**/*.py\").",
        "parameters": {
            "pattern": {
                "type": "string",
                "required": True,
                "description": "Python regular expression to search for in each line.",
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. \"**/*.py\", \"src/**/*.ts\"). Defaults to all text files.",
            },
            "head_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "description": "Maximum matches to return (default 250).",
            },
            "ignore_case": {
                "type": "boolean",
                "description": "Set to true for case-insensitive search (default false).",
            },
            "context_before": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": "Lines to show before each match.",
            },
            "context_after": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": "Lines to show after each match.",
            },
            "context_around": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": "Lines to show before and after each match (shorthand for setting both).",
            },
        },
        "examples": [
            '{"pattern": "^def calculate\\\\("}',
            '{"pattern": "class.*View", "glob": "**/*.py", "head_limit": 50}',
            '{"pattern": "TODO", "ignore_case": true, "glob": "**/*.py"}',
            '{"pattern": "def handle", "context_around": 3, "glob": "src/**/*.py"}',
        ],
    },
    ToolName.RUN_TESTS: {
        "description": "Run a self-test or diagnostic command in the repository. Allowed: pytest, python -m pytest, python -c, python <script>.py, git diff/status/log. Blocked: curl, rm, git push/commit, pip install, sudo.",
        "parameters": {
            "command": {
                "type": "string",
                "required": True,
                "description": "Shell command to run. Use single-quoted strings or shlex-safe syntax.",
            },
            "description": {
                "type": "string",
                "description": "Brief description of what this command does and why.",
            },
        },
        "examples": [
            '{"command": "pytest tests/test_main.py", "description": "Run the main test suite"}',
            '{"command": "python -c \\"import django; print(django.VERSION)\\"", "description": "Check Django version"}',
            '{"command": "git diff", "description": "Review pending changes"}',
            '{"command": "git log --oneline -5", "description": "Check recent commits"}',
        ],
    },
}
