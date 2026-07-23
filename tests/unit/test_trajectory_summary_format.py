import json
from pathlib import Path

from coding_agent.trajectory_exporter import convert_trajectory_to_summary_format


def test_summary_trajectory_keeps_all_search_code_matches(tmp_path: Path):
    matches = [
        {"path": f"file_{idx}.py", "line": idx, "text": "needle"}
        for idx in range(1, 8)
    ]
    trajectory_jsonl = tmp_path / "trajectory.jsonl"
    trajectory_jsonl.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "action_type": "model",
                        "reasoning_summary": "search for needle",
                    }
                ),
                json.dumps(
                    {
                        "action_type": "tool_result",
                        "tool_call": {
                            "tool_name": "search_code",
                            "input": {"pattern": "needle"},
                            "status": "ok",
                            "output_summary": "found 7 matches",
                        },
                        "tool_result": {
                            "output": {
                                "matches": matches,
                                "truncated": False,
                            }
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "trajectory.json"
    convert_trajectory_to_summary_format(
        trajectory_jsonl=trajectory_jsonl,
        task_id="repo__issue-1",
        issue="Fix it.",
        final_diff="",
        resolved=False,
        output_path=output_path,
    )

    trajectory = json.loads(output_path.read_text(encoding="utf-8"))
    observation = trajectory["steps"][0]["observation"]

    assert observation["matches"] == 7
    assert observation["results"] == matches
    assert observation["truncated"] is False
