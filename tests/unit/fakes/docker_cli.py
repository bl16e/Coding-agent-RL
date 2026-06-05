from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeDockerCli:
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def record(self, *command: str) -> None:
        self.commands.append(command)
