from __future__ import annotations

import json
import posixpath
import re
import shlex
import time
from typing import Any

from coding_agent.models import Outcome, ToolName
from coding_agent.sandbox_manager import DockerCli, DockerCommandError, DockerCommandTimeout
from coding_agent.tools.result import ToolExecutionResult


def _repo_file_path(repo_path: str, requested_path: str) -> str:
    if not requested_path:
        raise ValueError("path is required")
    relative = requested_path.lstrip("/")
    normalized = posixpath.normpath(posixpath.join(repo_path, relative))
    repo_root = posixpath.normpath(repo_path)
    if normalized != repo_root and not normalized.startswith(repo_root.rstrip("/") + "/"):
        raise ValueError("path escapes workspace")
    return normalized


def _docker_error(tool_name: ToolName, exc: Exception) -> ToolExecutionResult:
    return ToolExecutionResult(tool_name, Outcome.ERROR, str(exc))


def _blocked_command_message(command_name: str) -> str:
    if command_name in ("grep", "awk", "sed"):
        reason = "code/content search must use the structured repository search tool."
        use = 'search({"pattern": "<regex>"}) and read results with match_type="content".'
    elif command_name == "find":
        reason = "file discovery must use repo-scoped tools, not shell find."
        use = 'search({"pattern": "<filename_or_path_regex>"}) and read results with match_type="path".'
    elif command_name in ("cat", "head", "tail", "less", "more"):
        reason = "file inspection must use the structured file reader."
        use = 'read_file({"file_path": "<path>", "view_range": [start, end]}).'
    elif command_name == "git":
        reason = "git history/status inspection is not allowed for teacher trajectories."
        use = "work only from the current working tree with read_file/search."
    else:
        reason = "this executable is not allowed in execute_bash."
        use = "use the structured repository tools or a direct test command."
    return (
        f"Rejected: `{command_name}` is not allowed in execute_bash.\n"
        f"Reason: {reason}\n"
        f"Use: {use}\n"
        "This rejected attempt may disqualify the trajectory from SFT."
    )


def _blocked_syntax_message(reason: str) -> str:
    return (
        "Rejected: this shell syntax is not allowed in execute_bash.\n"
        f"Reason: {reason}\n"
        "Use: call read_file/search for inspection and run pytest or python commands directly.\n"
        "This rejected attempt may disqualify the trajectory from SFT."
    )


SHELL_REDIRECTION_TOKENS = {">", ">>", "<", "<<", "<<<", ">&", "<&", "2>", "2>>"}
REDIRECTION_TOKEN_PATTERN = re.compile(r"^\d*(?:>>?|<<?|>&|<&).*$")


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return [command]


def _has_command_substitution(command: str) -> bool:
    in_single_quote = False
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'":
            in_single_quote = not in_single_quote
            continue
        if in_single_quote:
            continue
        if char == "`":
            return True
        if char == "$" and command[index : index + 2] == "$(":
            return True
    return False


def _is_allowed_stderr_redirect(tokens: list[str], index: int) -> int:
    token = tokens[index]
    if token == "2>&1":
        return index + 1
    if token == "2" and tokens[index : index + 3] == ["2", ">&", "1"]:
        return index + 3
    if token in {"2>/dev/null", "2>>/dev/null"}:
        return index + 1
    if tokens[index : index + 2] in (["2>", "/dev/null"], ["2>>", "/dev/null"]):
        return index + 2
    if tokens[index : index + 3] in (["2", ">", "/dev/null"], ["2", ">>", "/dev/null"]):
        return index + 3
    return index


def _blocked_redirection_reason(tokens: list[str]) -> str | None:
    index = 0
    while index < len(tokens):
        next_index = _is_allowed_stderr_redirect(tokens, index)
        if next_index != index:
            index = next_index
            continue
        token = tokens[index]
        if token in {"<<", "<<<"}:
            return "heredocs are not allowed."
        if token in SHELL_REDIRECTION_TOKENS or REDIRECTION_TOKEN_PATTERN.match(token):
            return "redirection is not allowed except stderr suppression to /dev/null or 2>&1."
        index += 1
    return None


def _preflight_execute_bash(command: str, blocked_commands: set[str]) -> str | None:
    tokens = _shell_tokens(command)
    if _has_command_substitution(command):
        return _blocked_syntax_message("command substitution hides commands from the harness.")
    if not _pipes_only_clip_with_head_tail(command):
        return _blocked_syntax_message("pipes are allowed only when piping output to head or tail.")
    if redirection_reason := _blocked_redirection_reason(tokens):
        return _blocked_syntax_message(redirection_reason)

    subcommands = re.split(r"&&|;|\|\|", command)
    for subcmd in subcommands:
        try:
            parts = shlex.split(subcmd.strip())
        except ValueError:
            parts = subcmd.strip().split()
        if not parts:
            continue
        sub_first = parts[0]
        if sub_first in blocked_commands:
            return _blocked_command_message(sub_first)
    return None


def _pipes_only_clip_with_head_tail(command: str) -> bool:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return "|" not in command.replace("||", "")

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token not in {"|", "|&"}:
            index += 1
            continue
        if token == "|" and index + 1 < len(tokens) and tokens[index + 1] == "|":
            index += 2
            continue
        target_index = index + 1
        while target_index < len(tokens) and tokens[target_index] in {"env", "time", "timeout"}:
            target_index += 1
        if target_index >= len(tokens):
            return False
        executable = posixpath.basename(tokens[target_index]).lower()
        if executable not in {"head", "tail"}:
            return False
        index = target_index + 1
    return True


class ContainerToolExecutor:
    """Execute tools as standalone scripts inside a Docker container.

    Tool scripts are installed at /usr/local/bin/ in the container.
    Function calls are converted to CLI commands (R2E-Gym pattern):

        read_file --file_path /testbed/src/main.py --offset 10
        apply_patch update --path /testbed/src/main.py --old_string ... --new_string ...
        search --pattern "def foo" --glob "**/*.py"
        bash -lc "<command>"
        finish --result "done"

    execute_bash is the only tool that does NOT have a script 鈥?it runs
    bash directly.
    """

    _BLOCKED_BASH_COMMANDS = {
        # Dangerous operations
        "git", "ipython", "jupyter", "nohup",
        # File reading — use read_file instead
        "cat", "head", "tail", "less", "more",
        # Code search — use search instead
        "grep", "find", "awk", "sed",
    }
    _BASH_TIMEOUT = 30.0
    _SCRIPT_TIMEOUT = 60.0
    _BASH_ENV = "export PYTHONWARNINGS=ignore && "

    def __init__(
        self,
        *,
        docker: DockerCli,
        container_name: str,
        repo_path: str,
    ) -> None:
        self._docker = docker
        self._container_name = container_name
        self._repo_path = repo_path

    # -- dispatch -----------------------------------------------------------

    def execute(self, tool_name: ToolName, tool_input: dict[str, Any]) -> ToolExecutionResult:
        if tool_name is ToolName.EXECUTE_BASH:
            return self._execute_bash(tool_input)
        if tool_name is ToolName.FINISH:
            return self._finish(tool_input)
        if tool_name in (ToolName.READ_FILE, ToolName.APPLY_PATCH, ToolName.SEARCH, ToolName.SEARCH_CODE):
            return self._run_tool_script(tool_name, tool_input)
        raise ValueError(f"unsupported tool: {tool_name}")

    # -- CLI conversion -----------------------------------------------------

    @staticmethod
    def _to_cli_command(tool_name: ToolName, tool_input: dict[str, Any]) -> str:
        """Convert a function call to a CLI command string."""
        if tool_name is ToolName.READ_FILE:
            fp = shlex.quote(str(tool_input.get("file_path", "")))
            cmd = f"read_file --file_path {fp}"
            vr = tool_input.get("view_range")
            if vr and len(vr) == 2:
                cmd += f" --view_range {int(vr[0])} {int(vr[1])}"
            return cmd

        if tool_name is ToolName.APPLY_PATCH:
            fp = shlex.quote(str(tool_input.get("path", "")))
            old_raw = str(tool_input.get("old_string", ""))
            new = shlex.quote(str(tool_input.get("new_string", "")))
            if old_raw:
                old = shlex.quote(old_raw)
                return f"apply_patch --path {fp} --old_string {old} --new_string {new}"
            return f"apply_patch --path {fp} --new_string {new}"

        if tool_name in (ToolName.SEARCH, ToolName.SEARCH_CODE):
            pattern = shlex.quote(str(tool_input.get("pattern", "")))
            cmd = f"search --pattern {pattern}"
            glob_pat = tool_input.get("glob")
            if glob_pat:
                cmd += f" --glob {shlex.quote(str(glob_pat))}"
            head_limit = tool_input.get("head_limit")
            if head_limit is not None:
                cmd += f" --head_limit {int(head_limit)}"
            return cmd

        raise ValueError(f"cannot convert to CLI: {tool_name}")

    # -- script execution ---------------------------------------------------

    def _run_tool_script(
        self, tool_name: ToolName, tool_input: dict[str, Any],
    ) -> ToolExecutionResult:
        cli_cmd = self._to_cli_command(tool_name, tool_input)
        started = time.monotonic()
        try:
            result = self._docker.exec(
                self._container_name,
                ["bash", "-lc", self._BASH_ENV + cli_cmd],
                timeout_seconds=self._SCRIPT_TIMEOUT,
                workdir=self._repo_path,
                check=False,
            )
        except DockerCommandTimeout:
            duration = time.monotonic() - started
            return ToolExecutionResult(
                tool_name, Outcome.TIMEOUT,
                f"tool timed out after {self._SCRIPT_TIMEOUT}s",
                output={"stdout": "", "stderr": "", "duration_seconds": duration},
            )
        except DockerCommandError as exc:
            duration = time.monotonic() - started
            output_text = exc.result.stdout.rstrip() + "\n" + exc.result.stderr.rstrip()
            return ToolExecutionResult(
                tool_name, Outcome.FAILED,
                f"tool failed (exit {exc.result.returncode})",
                output={
                    "stdout": exc.result.stdout.strip(),
                    "stderr": exc.result.stderr.strip(),
                    "exit_code": exc.result.returncode,
                    "duration_seconds": duration,
                },
            )

        duration = time.monotonic() - started
        stdout = result.stdout.rstrip()
        stderr = result.stderr.rstrip()

        if result.returncode != 0:
            return ToolExecutionResult(
                tool_name, Outcome.FAILED,
                stderr.splitlines()[-1] if stderr else f"exit {result.returncode}",
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": result.returncode,
                    "duration_seconds": duration,
                },
            )

        # Parse JSON output for search.
        output_data: dict[str, Any] = {"stdout": stdout, "stderr": stderr,
                                         "exit_code": 0, "duration_seconds": duration}
        if tool_name in (ToolName.SEARCH, ToolName.SEARCH_CODE):
            try:
                parsed = json.loads(stdout) if stdout else {}
                if isinstance(parsed, dict):
                    output_data.update(parsed)
            except json.JSONDecodeError:
                output_data["raw_output"] = stdout

        output_summary = stdout[:200] if stdout else "(no output)"
        return ToolExecutionResult(tool_name, Outcome.OK, output_summary, output=output_data)

    # -- execute_bash -------------------------------------------------------

    def _execute_bash(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        command = str(tool_input.get("command", "")).strip()
        if not command:
            return ToolExecutionResult(
                ToolName.EXECUTE_BASH, Outcome.REJECTED,
                "command must not be empty",
            )
        if rejection := _preflight_execute_bash(command, self._BLOCKED_BASH_COMMANDS):
            return ToolExecutionResult(
                ToolName.EXECUTE_BASH, Outcome.REJECTED, rejection,
            )
        started = time.monotonic()
        try:
            result = self._docker.exec(
                self._container_name,
                ["bash", "-lc", self._BASH_ENV + command],
                timeout_seconds=self._BASH_TIMEOUT,
                workdir=self._repo_path,
                check=False,
            )
        except DockerCommandTimeout:
            duration = time.monotonic() - started
            return ToolExecutionResult(
                ToolName.EXECUTE_BASH, Outcome.TIMEOUT,
                f"command timed out after {self._BASH_TIMEOUT}s",
                output={"stdout": "", "stderr": "", "exit_code": -1, "duration_seconds": duration},
            )
        except DockerCommandError as exc:
            duration = time.monotonic() - started
            return ToolExecutionResult(
                ToolName.EXECUTE_BASH, Outcome.FAILED,
                f"command failed (exit {exc.result.returncode})",
                output={
                    "stdout": exc.result.stdout.strip(),
                    "stderr": exc.result.stderr.strip(),
                    "exit_code": exc.result.returncode,
                    "duration_seconds": duration,
                },
            )
        duration = time.monotonic() - started
        stdout = result.stdout.rstrip()
        stderr = result.stderr.rstrip()
        output_summary = stdout[:200] if stdout else stderr[:200] or "(no output)"
        if result.returncode != 0:
            # Non-zero exit with stdout → tool likely produced useful output
            # despite non-zero exit (e.g. pytest, sqlfluff fix). Treat as OK
            # so the model reads the output rather than retrying.
            if stdout:
                return ToolExecutionResult(
                    ToolName.EXECUTE_BASH, Outcome.OK,
                    f"[exit {result.returncode}] {output_summary}",
                    output={"stdout": stdout, "stderr": stderr,
                            "exit_code": result.returncode, "duration_seconds": duration},
                )
            # No stdout at all → genuine failure
            return ToolExecutionResult(
                ToolName.EXECUTE_BASH, Outcome.FAILED,
                f"[exit {result.returncode}] {stderr[:200] if stderr else '(no output)'}",
                output={"stdout": stdout, "stderr": stderr,
                        "exit_code": result.returncode, "duration_seconds": duration},
            )
        return ToolExecutionResult(
            ToolName.EXECUTE_BASH, Outcome.OK, output_summary,
            output={"stdout": stdout, "stderr": stderr,
                    "exit_code": 0, "duration_seconds": duration},
        )

    # -- finish --------------------------------------------------------------

    def _finish(self, tool_input: dict[str, Any]) -> ToolExecutionResult:
        result_msg = str(tool_input.get("result", "")).strip()
        summary = result_msg or "task submitted"
        return ToolExecutionResult(
            ToolName.FINISH, Outcome.OK, summary,
            output={"submission": result_msg},
        )


def install_tool_scripts(container_name: str, docker: DockerCli) -> list[str]:
    """Copy standalone tool scripts into the container at /usr/local/bin/.

    Returns the list of installed command names.
    """
    import os
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parent / "scripts"
    if not scripts_dir.is_dir():
        raise FileNotFoundError(f"tool scripts directory not found: {scripts_dir}")

    installed: list[str] = []
    for script in sorted(scripts_dir.glob("*.py")):
        if script.name == "__init__.py":
            continue
        name = script.stem
        try:
            docker.exec(
                container_name,
                ["mkdir", "-p", "/usr/local/bin"],
                check=False,
            )
            # Copy via docker cp
            import subprocess
            subprocess.run(
                ["docker", "cp", str(script),
                 f"{container_name}:/usr/local/bin/{name}"],
                check=True, capture_output=True, text=True,
            )
            docker.exec(
                container_name,
                ["chmod", "+x", f"/usr/local/bin/{name}"],
                check=False,
            )
            installed.append(name)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Failed to install tool script {name}: {exc.stderr}"
            ) from exc

    return installed
