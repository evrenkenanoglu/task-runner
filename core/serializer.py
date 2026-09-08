import json
import platform
from typing import Dict, List, Optional, Union
from invoke import Context

IS_WINDOWS = platform.system() == "Windows"

# ANSI Color Codes
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
GRAY = "\033[90m"

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

        # 1. Numbered Command List
        print(f"\n{BOLD}{CYAN}[COMMAND LIST]:{RESET}")
        for idx, cmd in enumerate(cmd_list, start=1):
            print(f"  {YELLOW}{idx}.{RESET} {GREEN}{cmd}{RESET}")

        # 2. Serialized JSON Representation
        # print(f"\n{BOLD}{CYAN}[Command Serialized (JSON)]:{RESET}")
        # print(f"  {MAGENTA}{serialized_json}{RESET}")

        # 3. Serialized Shell String
        print(f"\n{BOLD}{CYAN}[COMMAND SERIALIZED]:{RESET}")
        print(f"  {BOLD}{GREEN}{serialized_str}{RESET}\n")

        if not dry_run:
            c.run(
                serialized_str,
                env=self.env,
                pty=self.pty,
                encoding="utf-8",
            )
        else:
            print(f"{BOLD}{YELLOW}[DRY-RUN]: Execution skipped.{RESET}\n")