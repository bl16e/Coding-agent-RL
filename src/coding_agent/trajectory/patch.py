from __future__ import annotations

import difflib
from pathlib import Path


def snapshot_workspace(workspace: str | Path) -> dict[str, str]:
    """捕获确定性的文本文件快照，用于后续生成 patch。

    快照 key 使用工作区相对 POSIX 路径，保证 Windows 宿主机和 Linux 容器产物格式一致。
    """

    root = Path(workspace).resolve()
    snapshot: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # MVP 只导出文本 unified diff。非文本文件直接跳过，避免把二进制内容写成
            # 无效 patch。
            continue
        snapshot[path.relative_to(root).as_posix()] = content
    return snapshot


def generate_unified_patch(before: dict[str, str], after: dict[str, str]) -> str:
    """根据运行前后快照生成 SWE-Bench prediction 使用的 patch。"""

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
