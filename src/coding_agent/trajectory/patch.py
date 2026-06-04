from __future__ import annotations

import difflib
from pathlib import Path


def snapshot_workspace(workspace: str | Path) -> dict[str, str]:
    """Capture a deterministic text snapshot for later patch generation."""

    root = Path(workspace).resolve()
    snapshot: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # The MVP exports text unified diffs only. Non-text files are skipped
            # instead of being corrupted into an invalid patch.
            continue
        snapshot[path.relative_to(root).as_posix()] = content
    return snapshot


def generate_unified_patch(before: dict[str, str], after: dict[str, str]) -> str:
    """Generate the SWE-Bench prediction patch from two text snapshots."""

    chunks: list[str] = []
    for relative_path in sorted(set(before) | set(after)):
        old = before.get(relative_path, "")
        new = after.get(relative_path, "")
        if old == new:
            continue
        chunks.extend(
            difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
    return "".join(line + "\n" for line in chunks)
