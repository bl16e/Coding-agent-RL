from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class TextIOError(Exception):
    """Base error for repository text I/O."""


class BinaryFileError(TextIOError):
    """Raised when bytes do not look like editable text."""


class TextDecodeError(TextIOError):
    """Raised when bytes cannot be decoded with supported encodings."""


SUPPORTED_ENCODINGS = ("utf-8", "gbk")
DEFAULT_PAGE_LINES = 1000


@dataclass(frozen=True)
class TextFile:
    content: str
    encoding: str
    newline: str

    @property
    def total_lines(self) -> int:
        return len(self.content.splitlines())


@dataclass(frozen=True)
class TextPage:
    content: str
    encoding: str
    newline: str
    line_start: int
    line_end: int
    total_lines: int
    truncated: bool

    def to_output(self) -> dict[str, object]:
        return {
            "content": self.content,
            "encoding": self.encoding,
            "newline": self.newline,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "total_lines": self.total_lines,
            "truncated": self.truncated,
        }


def _looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    control = 0
    for byte in data:
        if byte < 32 and byte not in (9, 10, 12, 13):
            control += 1
    return control / len(data) > 0.30


def detect_newline(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    normalized = data.replace(b"\r\n", b"")
    lf = normalized.count(b"\n")
    cr = normalized.count(b"\r")
    kinds = sum(1 for count in (crlf, lf, cr) if count)
    if kinds == 0:
        return "none"
    if kinds > 1:
        return "mixed"
    if crlf:
        return "crlf"
    if cr:
        return "cr"
    return "lf"


def read_text_file(path: str | Path) -> TextFile:
    data = Path(path).read_bytes()
    if _looks_binary(data):
        raise BinaryFileError("binary file is not supported")
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return TextFile(data.decode(encoding), encoding, detect_newline(data))
        except UnicodeDecodeError:
            continue
    raise TextDecodeError(f"file is not supported text; tried {', '.join(SUPPORTED_ENCODINGS)}")


def _newline_sequence(newline: str) -> str | None:
    return {"lf": "\n", "crlf": "\r\n", "cr": "\r"}.get(newline)


def normalize_newlines(content: str, newline: str) -> str:
    sequence = _newline_sequence(newline)
    if sequence is None:
        return content
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", sequence)


def write_text_file(path: str | Path, content: str, *, encoding: str, newline: str) -> None:
    normalized = normalize_newlines(content, newline)
    Path(path).write_bytes(normalized.encode(encoding))


def page_text(text_file: TextFile, bounds: tuple[int, int] | None, *, default_limit: int = DEFAULT_PAGE_LINES) -> TextPage:
    lines = text_file.content.splitlines(keepends=True)
    total_lines = len(text_file.content.splitlines())
    if bounds is None:
        start = 1
        end = min(default_limit, max(total_lines, 1))
    else:
        start, end = bounds
    selected = "".join(lines[start - 1 : end])
    actual_end = min(end, total_lines)
    truncated = start > 1 or end < total_lines
    if total_lines == 0:
        actual_end = 0
        truncated = False
    return TextPage(
        content=selected,
        encoding=text_file.encoding,
        newline=text_file.newline,
        line_start=start if total_lines else 0,
        line_end=actual_end,
        total_lines=total_lines,
        truncated=truncated,
    )
