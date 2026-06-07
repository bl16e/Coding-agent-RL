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
        "description": "Read a UTF-8 text file from the repository. Use line windows for large files.",
        "parameters": {
            "path": {
                "type": "string",
                "required": True,
                "description": "Repository-relative file path.",
            },
            "line": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional 1-based start line.",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional inclusive end line.",
            },
            "offset": {
                "type": "integer",
                "minimum": 1,
                "description": "Alias for 1-based start line.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Number of lines to read with offset.",
            },
        },
        "examples": [
            '{"path": "src/main.py"}',
            '{"path": "README.md", "line": 10, "end_line": 50}',
            '{"path": "config.json", "offset": 1, "limit": 20}',
        ],
    },
    ToolName.APPLY_PATCH: {
        "description": "Modify the repository by applying a patch. Supports adding files, editing with exact string replacement, and moving files.",
        "parameters": {
            "type": {
                "type": "string",
                "required": True,
                "enum": ["add_file", "update", "move"],
                "description": "Operation type: add_file (create new), update (replace old_string with new_string), move (rename).",
            },
            "path": {
                "type": "string",
                "description": "File path for add_file and update operations.",
            },
            "content": {
                "type": "string",
                "description": "Complete file content for add_file operation.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to replace for update operation (must match once).",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text for update operation.",
            },
            "old_path": {
                "type": "string",
                "description": "Source path for move operation.",
            },
            "new_path": {
                "type": "string",
                "description": "Destination path for move operation.",
            },
        },
        "examples": [
            '{"type": "add_file", "path": "tests/test_calc.py", "content": "import pytest\\n..."}',
            '{"type": "update", "path": "src/main.py", "old_string": "def substract(a, b):", "new_string": "def subtract(a, b):"}',
            '{"type": "move", "old_path": "src/old.py", "new_path": "src/new.py"}',
        ],
    },
    ToolName.SEARCH_CODE: {
        "description": "Search repository text files for an exact text query.",
        "parameters": {
            "query": {
                "type": "string",
                "required": True,
                "description": "Exact text to search for.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum matches (default 20).",
            },
        },
        "examples": [
            '{"query": "def calculate"}',
            '{"query": "import numpy", "max_results": 50}',
        ],
    },
    ToolName.RUN_TESTS: {
        "description": "Run one exact validation command from the allowed command list.",
        "parameters": {
            "command": {
                "type": "string",
                "required": True,
                "description": "Exact allowed test command to run.",
            },
        },
        "examples": ['{"command": "pytest tests/test_main.py"}'],
    },
}

# Final action schema (not a tool, but follows similar pattern)
FINAL_ACTION_SCHEMA = {
    "description": "Finish the run after solving, failing, or exhausting useful work.",
    "parameters": {
        "final_status": {
            "type": "string",
            "required": True,
            "enum": ["solved", "failed", "incomplete", "errored"],
            "description": "Terminal status of the run.",
        },
        "final_message": {
            "type": "string",
            "description": "Optional explanation of the outcome.",
        },
    },
    "examples": ['{"final_status": "solved", "final_message": "All tests passing"}'],
}
