#!/usr/bin/env python3
"""
Read a UTF-8 text file from the repository. Output is formatted with line
numbers (cat -n style). Shows the first 300 lines by default.
Use --view_range to show a specific line range.
Use --offset to start at a specific line.

If the path is a directory, lists non-hidden files and directories
up to 2 levels deep.

Parameters:
  --file_path  (string, required): Absolute path to the file or directory.
  --offset     (integer, optional): 1-based start line number (default 1).
  --page_lines (integer, optional): Lines per page (default 300).
  --view_range (int int): Show lines from START to END (-1 = to end).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MAX_CHARS = 50000


def looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    control = sum(1 for b in data if b < 32 and b not in (9, 10, 12, 13))
    return control / len(data) > 0.30


def read_text(p: Path) -> str:
    if p.is_dir():
        raise IsADirectoryError(f"Is a directory: {p}")
    data = p.read_bytes()
    if looks_binary(data):
        raise ValueError("binary file is not supported")
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError("file is not supported text; tried utf-8, gbk")


def _cat_numbered(text: str, start_line: int = 1) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    end = start_line + len(lines) - 1
    width = max(4, len(str(end)))
    return "\n".join(
        f"{start_line + i:>{width}} {line}" for i, line in enumerate(lines)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read a file or list a directory."
    )
    parser.add_argument(
        "--file_path", required=True, help="Absolute path to the file or directory."
    )
    parser.add_argument(
        "--offset", type=int, default=1, help="1-based start line (default 1)."
    )
    parser.add_argument(
        "--page_lines", type=int, default=300,
        help="Lines per page (default 300)."
    )
    parser.add_argument(
        "--view_range", nargs=2, type=int, default=None,
        help="Show lines from START to END (-1 = to end of file)."
    )
    args = parser.parse_args()

    path = Path(args.file_path)

    if path.is_dir():
        import subprocess
        result = subprocess.run(
            ["find", str(path), "-maxdepth", "2", "-not", "-path", "*/.*"],
            capture_output=True, text=True,
        )
        print(result.stdout.strip() or f"(empty directory: {args.file_path})")
        return

    if not path.exists():
        print(f"ERROR: file not found: {args.file_path}", file=sys.stderr)
        sys.exit(1)

    try:
        content = read_text(path)
    except (ValueError, IsADirectoryError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    lines = content.splitlines()
    total = len(lines)

    if args.view_range and len(args.view_range) == 2:
        start, end = args.view_range
        end = total if end == -1 else min(end, total)
    else:
        start = max(1, args.offset)
        end = min(start + args.page_lines - 1, max(total, 1))

    selected = "\n".join(lines[start - 1:end])
    output = _cat_numbered(selected, start)

    truncated = (
        (args.offset > 1)
        or (args.view_range and end < total)
        or (not args.view_range and end < total)
    )

    if len(output) > MAX_CHARS:
        output = output[:MAX_CHARS]
        truncated = True

    if truncated and total > 0:
        remaining = total - end
        output += f"\n... [truncated, {remaining} lines remaining]"

    print(output)


if __name__ == "__main__":
    main()
