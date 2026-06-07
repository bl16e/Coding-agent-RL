from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def convert_trajectory_to_summary_format(
    *,
    trajectory_jsonl: Path,
    task_id: str,
    issue: str,
    final_diff: str,
    resolved: bool,
    output_path: Path,
) -> None:
    """Convert detailed JSONL trajectory to simplified summary format."""

    # Read JSONL trajectory
    with open(trajectory_jsonl, "r", encoding="utf-8") as f:
        raw_steps = [json.loads(line) for line in f if line.strip()]

    # Group model decisions with their tool results
    steps = []
    i = 0
    step_counter = 0

    while i < len(raw_steps):
        current = raw_steps[i]

        # Skip if not a model decision
        if current.get("action_type") != "model":
            i += 1
            continue

        thought = current.get("reasoning_summary", "")

        # Check if next step is a tool result
        if i + 1 < len(raw_steps) and raw_steps[i + 1].get("action_type") == "tool_result":
            tool_result = raw_steps[i + 1]
            tool_call = tool_result.get("tool_call", {})
            tool_name = tool_call.get("tool_name", "")
            tool_input = tool_call.get("input", {})

            # Clean input: remove reasoning fields
            args = {
                k: v for k, v in tool_input.items()
                if k not in ("reasoning_summary", "next_intent", "tool_selection_reason")
            }

            # Extract observation
            result = tool_result.get("tool_result", )
            observation = _format_observation(tool_name, result)

            steps.append({
                "step": step_counter,
                "thought": thought,
                "action": {
                    "tool": tool_name,
                    "args": args,
                },
                "observation": observation,
            })

            step_counter += 1
            i += 2  # Skip both model and tool_result
        else:
            # Final step without tool call
            i += 1

    # Calculate reward based on resolution
    reward = 1.0 if resolved else 0.0

    # Build summary
    summary = {
        "task_id": task_id,
        "issue": issue,
        "steps": steps,
        "final_diff": final_diff,
        "resolved": resolved,
        "reward": reward,
    }

    # Write summary
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


def _format_observation(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Format tool result into observation dict."""

    if tool_name == "read_file":
        output = result.get("output", {})
        return {"content": output.get("content", "")}

    elif tool_name == "apply_patch":
        output = result.get("output", {})
        patch = output.get("patch", "")
        modifications = result.get("modifications", [])
        if patch:
            return {"patch": patch}
        if modifications:
            mod = modifications[0]
            return {
                "status": "success" if mod.get("write_status") == "ok" else "failed",
                "path": mod.get("path", ""),
            }
        return {"status": "applied"}

    elif tool_name == "search_code":
        output = result.get("output", {})
        matches = output.get("matches", [])
        return {
            "matches": len(matches),
            "results": matches[:5],  # Limit to first 5 for brevity
        }

    elif tool_name == "run_tests":
        test_result = result.get("test_result", {})
        return {
            "status": test_result.get("status", ""),
            "passed": test_result.get("status") == "passed",
            "output": test_result.get("output_summary", "")[:200],  # Truncate
        }

    # Generic fallback
    return {"raw": result}
