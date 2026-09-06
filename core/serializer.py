import json
import platform
from typing import Dict, List, Optional, Union
from invoke import Context

IS_WINDOWS = platform.system() == "Windows"

class CommandSerializer:
    """Encapsulates command chaining, formatting, logging, and execution."""

    def __init__(
        self,
        prefix_commands: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        separator: str = " && ",
        pty: Optional[bool] = None,
    ) -> None:
        self.separator = separator
        self.env = env
        self.pty = (not IS_WINDOWS) if pty is None else pty
        self._commands: List[str] = [cmd for cmd in (prefix_commands or []) if cmd]

    def add(self, command: Union[str, List[str]], extra: str = "") -> "CommandSerializer":
        if isinstance(command, list):
            self._commands.extend(command)
        else:
            self._commands.append(command)

        if extra:
            self._commands[-1] = f"{self._commands[-1]} {extra}".strip()

        return self

    def to_list(self) -> List[str]:
        return list(self._commands)

    def serialize(self) -> str:
        return self.separator.join(self._commands)

    def run(self, c: Context, dry_run: bool = False) -> None:
        cmd_list = self.to_list()
        serialized_json = json.dumps(cmd_list)
        serialized_str = self.serialize()

        print("\n[Command List]:")
        for idx, cmd in enumerate(cmd_list, start=1):
            print(f"{idx}. {cmd}")

        # print(f"\n[Command Serialized (JSON)]:\n{serialized_json}")
        print(f"\n[Command Serialized (String)]:\n{serialized_str}\n")

        if not dry_run:
            c.run(serialized_str, env=self.env, pty=self.pty)
        else:
            print("[DRY-RUN]: Execution skipped.")