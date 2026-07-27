#!/usr/bin/env python3
"""
Search repository text files with a regular expression. Returns matching
lines in JSON format with optional context. Uses ripgrep (rg) if available,
otherwise falls back to pure Python search.

Parameters:
  --pattern      (string, required): Python regex to search for.
  --glob         (string, optional): File pattern filter (e.g. "**/*.py").
  --head_limit   (integer, optional): Max matches to return (default 250).
  --ignore_case  (flag): Case-insensitive search.
  --context_before (integer, optional): Lines before each match.
  --context_after  (integer, optional): Lines after each match.
  --context_around (integer, optional): Lines before and after each match.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    control = sum(1 for b in data if b < 32 and b not in (9, 10, 12, 13))
    return control / len(data) > 0.30


def search_with_rg(
    pattern: str,
    path: str,
    head_limit: int,
    ignore_case: bool,
    glob_pat: str | None,
    ctx_before: int,
    ctx_after: int,
    ctx_around: int,
) -> dict | None:
    """Try ripgrep. Returns None if rg is unavailable."""
    try:
        probe = subprocess.run(
            ["sh", "-lc", "command -v rg >/dev/null 2>&1"],
            capture_output=True, check=False,
        )
        if probe.returncode != 0:
            return None

        cmd = ["rg", "--json", "--line-number", "--max-count", str(head_limit)]
        if ignore_case:
            cmd.append("--ignore-case")
        if ctx_before > 0:
            cmd.extend(["-B", str(ctx_before)])
        if ctx_after > 0:
            cmd.extend(["-A", str(ctx_after)])
        if ctx_around > 0:
            cmd.extend(["-C", str(ctx_around)])
        for d in [".git", ".venv", "venv", "node_modules", "build", "dist",
                   ".tox", "__pycache__", ".pytest_cache"]:
            cmd.extend(["--glob", f"!{d}/**"])
        if glob_pat:
            cmd.extend(["--glob", glob_pat])
        cmd.append(pattern)
        cmd.append(path)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    matches: list[dict] = []
    for line in result.stdout.splitlines():
        if len(matches) >= head_limit:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data") or {}
        path_text = ((data.get("path") or {}).get("text") or "").strip()
        line_text = ((data.get("lines") or {}).get("text") or "").rstrip("\r\n")
        matches.append({
            "path": path_text,
            "line": int(data.get("line_number") or 0),
            "text": line_text,
        })
    return {"matches": matches, "truncated": len(matches) >= head_limit, "engine": "rg"}


def _match_glob(rel_path: str, gpat: str) -> bool:
    if not gpat or gpat == "**/*":
        return True
    parts = gpat.split("/")
    rparts: list[str] = []
    prev_ds = False
    for part in parts:
        if part == "**":
            if rparts:
                rparts.append("/")
            rparts.append(r"(?:[^/]+/)*")
            prev_ds = True
        else:
            escaped = re.escape(part)
            escaped = escaped.replace(r"\*", "[^/]*")
            escaped = escaped.replace(r"\?", "[^/]")
            if rparts and not prev_ds:
                rparts.append("/")
            rparts.append(escaped)
            prev_ds = False
    regex = "^" + "".join(rparts) + "$"
    return bool(re.match(regex, rel_path))


def search_with_python(
    pattern: str,
    path: str,
    head_limit: int,
    ignore_case: bool,
    glob_pat: str | None,
    ctx_before: int,
    ctx_after: int,
    ctx_around: int,
) -> dict:
    flags = re.IGNORECASE if ignore_case else 0
    compiled = re.compile(pattern, flags)

    excluded = {".git", ".venv", "venv", "node_modules", "build", "dist",
                 ".tox", "__pycache__", ".pytest_cache"}
    has_context = ctx_before > 0 or ctx_after > 0 or ctx_around > 0
    root = Path(path)

    matches: list[dict] = []
    truncated = False
    for filepath in sorted(p for p in root.rglob("*") if p.is_file()):
        parts = set(filepath.relative_to(root).parts)
        if parts & excluded:
            continue
        if glob_pat:
            rel = filepath.relative_to(root).as_posix()
            if not _match_glob(rel, glob_pat):
                continue
        try:
            data = filepath.read_bytes()
            if looks_binary(data):
                continue
            for enc in ("utf-8", "gbk"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    pass
            else:
                continue
        except (OSError, UnicodeDecodeError):
            continue

        lines = text.splitlines()
        for idx, line in enumerate(lines, 1):
            if compiled.search(line):
                if len(matches) >= head_limit:
                    truncated = True
                    break
                entry = {
                    "path": filepath.relative_to(root).as_posix(),
                    "line": idx,
                    "text": line,
                }
                if has_context:
                    bc = max(ctx_before, ctx_around)
                    ac = max(ctx_after, ctx_around)
                    entry["context_before"] = [
                        {"line": i + 1, "text": lines[i]}
                        for i in range(max(0, idx - bc - 1), idx - 1)
                    ]
                    entry["context_after"] = [
                        {"line": i + 1, "text": lines[i]}
                        for i in range(idx, min(len(lines), idx + ac))
                    ]
                matches.append(entry)
        if truncated:
            break

    return {"matches": matches, "truncated": truncated, "engine": "python"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search repository text files with a regular expression."
    )
    parser.add_argument("--pattern", required=True, help="Python regex to search for.")
    parser.add_argument("--glob", default=None, help="File pattern filter.")
    parser.add_argument("--head_limit", type=int, default=250,
                        help="Max matches (default 250).")
    parser.add_argument("--ignore_case", action="store_true",
                        help="Case-insensitive search.")
    parser.add_argument("--context_before", type=int, default=0)
    parser.add_argument("--context_after", type=int, default=0)
    parser.add_argument("--context_around", type=int, default=0)
    args = parser.parse_args()

    search_path = os.getcwd()

    # Try ripgrep first
    rg_result = search_with_rg(
        args.pattern, search_path, args.head_limit, args.ignore_case,
        args.glob, args.context_before, args.context_after, args.context_around,
    )
    if rg_result is not None:
        print(json.dumps(rg_result, ensure_ascii=False))
        return

    # Fall back to Python
    py_result = search_with_python(
        args.pattern, search_path, args.head_limit, args.ignore_case,
        args.glob, args.context_before, args.context_after, args.context_around,
    )
    print(json.dumps(py_result, ensure_ascii=False))


if __name__ == "__main__":
    main()
