#!/usr/bin/env python3
"""
Modify or create files.

  Update (old_string non-empty):
    Finds old_string in the file and replaces it with new_string.
    old_string must appear exactly once. Copy it from read_file output
    for exact whitespace match. Include enough context to make it unique.

  Create (old_string empty or omitted):
    Writes new_string as the full file content.

State is persisted in /var/tmp/editor_state.json for undo support.

Parameters:
  --path       (string, required): Absolute path to the file.
  --old_string (string, optional): Text to replace. Empty = create/overwrite.
  --new_string (string, required): Replacement or full file content.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

STATE_FILE = "/var/tmp/editor_state.json"


def load_state() -> Dict[str, List[str]]:
    try:
        data = Path(STATE_FILE).read_text(encoding="utf-8")
        return {k: v for k, v in json.loads(data).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: Dict[str, List[str]]) -> None:
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(STATE_FILE).write_text(json.dumps(state), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Modify or create files.")
    parser.add_argument("--path", required=True, help="Absolute path to the file.")
    parser.add_argument("--old_string", default="",
                        help="Text to replace. Empty = create/overwrite.")
    parser.add_argument("--new_string", required=True,
                        help="Replacement or full file content.")
    args = parser.parse_args()

    path = Path(args.path)
    old = args.old_string
    new = args.new_string

    # --- Create mode ---
    if not old:
        path.parent.mkdir(parents=True, exist_ok=True)
        state = load_state()
        key = str(path)
        if key not in state:
            state[key] = []
        state[key].append("")  # mark as created by this tool
        save_state(state)
        path.write_text(new, encoding="utf-8")
        print(f"Created: {args.path}")
        return

    # --- Update mode ---
    if not path.exists():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    content = path.read_text(encoding="utf-8", errors="replace")
    count = content.count(old)
    if count == 0:
        lines = content.splitlines()
        scored = [
            (l, sum(1 for a, b in zip(old, l) if a == b)
             / max(len(old), len(l), 1))
            for l in lines
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        hints = [l[:120] for l, r in scored[:3] if r > 0.3]
        msg = f"ERROR: old_string not found in {args.path}"
        if hints:
            msg += "\nMost similar lines:\n" + "\n".join(
                f"  > {h}" for h in hints
            )
        print(msg, file=sys.stderr)
        sys.exit(1)
    if count > 1:
        print(
            f"ERROR: old_string appears {count} times in {args.path}. "
            "Add more surrounding context to make it unique.",
            file=sys.stderr,
        )
        sys.exit(1)

    state = load_state()
    key = str(path)
    if key not in state:
        state[key] = []
    state[key].append(content)
    save_state(state)

    path.write_text(content.replace(old, new, 1), encoding="utf-8")

    # Show snippet around the edit
    replacement_line = content.split(old)[0].count("\n")
    new_lines = new.splitlines()
    n_new = len(new_lines) if new_lines else 1
    snippet_start = max(0, replacement_line - 4)
    snippet_end = replacement_line + n_new + 4
    new_content = content.replace(old, new, 1)
    snippet = "\n".join(
        f"{snippet_start + i + 1:>4} {l}"
        for i, l in enumerate(new_content.splitlines()[snippet_start:snippet_end])
    )
    print(f"Patched: {args.path}\n{snippet}")


if __name__ == "__main__":
    main()
