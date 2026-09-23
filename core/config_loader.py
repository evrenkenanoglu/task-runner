import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List
import yaml

from core.config_resolver import (
    ConfigNode,
    deep_merge,
    expand_tokens,
    find_workspace_root,
    flatten_dict,
    resolve_config,
)

IS_WINDOWS = platform.system() == "Windows"
TOOL_DIR = Path(__file__).resolve().parent.parent

# Reconfigure parent process streams to UTF-8 on Windows
if IS_WINDOWS:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "__pycache__",
    ".idea",
    ".vscode",
    TOOL_DIR.name,
}

WORKSPACE_DIR = find_workspace_root(Path.cwd())


def _find_root_config() -> Path:
    """Find the root configuration file via environment variable or search paths."""
    env_override = os.environ.get("TASK_CONFIG_PATH")
    if env_override:
        custom_path = Path(env_override)
        return (
            custom_path
            if custom_path.is_absolute()
            else (WORKSPACE_DIR / custom_path).resolve()
        )

    candidates = [
        WORKSPACE_DIR / "configs" / "config_tasks.yaml",
        WORKSPACE_DIR / "config_tasks.yaml",
        WORKSPACE_DIR / "configs" / "config.yaml",
        WORKSPACE_DIR / "config.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return (WORKSPACE_DIR / "configs" / "config_tasks.yaml").resolve()


def _resolve_paths(paths_dict: Dict[str, Any]) -> Dict[str, Path]:
    """Convert all path strings into resolved pathlib.Path objects."""
    resolved = {}
    for key, val in paths_dict.items():
        if isinstance(val, str):
            p = Path(val)
            resolved[key] = (
                p.resolve() if p.is_absolute() else (WORKSPACE_DIR / p).resolve()
            )
        elif isinstance(val, Path):
            resolved[key] = val.resolve()
        else:
            resolved[key] = val
    return resolved


def load_config() -> ConfigNode:
    # 1. Base default configuration (task-runner defaults)
    default_cfg_path = TOOL_DIR / "default_config.yaml"
    base_data: Dict[str, Any] = {}
    if default_cfg_path.exists():
        with default_cfg_path.open("r", encoding="utf-8") as f:
            base_data = yaml.safe_load(f) or {}

    # 2. Root project configuration (resolved via config_resolver with SSoT inheritance)
    root_cfg_path = _find_root_config()
    root_data: Dict[str, Any] = {}
    if root_cfg_path.exists():
        root_data = resolve_config(
            config_path=root_cfg_path,
            workspace_root=WORKSPACE_DIR,
            return_node=False,
        )

    merged_config = deep_merge(base_data, root_data)

    # 3. Recursive discovery of all sub-module config files
    discovered_sub_configs: List[Path] = []
    for pattern in ["**/config_tasks.yaml"]:
        for path in WORKSPACE_DIR.glob(pattern):
            resolved_path = path.resolve()
            if resolved_path == root_cfg_path:
                continue
            if TOOL_DIR.resolve() in resolved_path.parents:
                continue
            if any(part in IGNORE_DIRS for part in resolved_path.parts):
                continue
            discovered_sub_configs.append(resolved_path)

    discovered_sub_configs = sorted(
        list(set(discovered_sub_configs)), key=lambda p: len(p.parts)
    )

    for sub_config_path in discovered_sub_configs:
        sub_data = resolve_config(
            config_path=sub_config_path,
            workspace_root=WORKSPACE_DIR,
            return_node=False,
        )
        merged_config = deep_merge(merged_config, sub_data)

    # 4. Multi-pass token resolution across the entire merged config tree
    root_str = str(WORKSPACE_DIR)
    tool_str = str(TOOL_DIR)

    for _ in range(5):
        context = flatten_dict(merged_config)

        # Inject standard root aliases
        context["workspace_dir"] = root_str
        context["project_root"] = root_str
        context["project_root_dir"] = root_str
        context["paths.workspace_dir"] = root_str
        context["tool_dir"] = tool_str
        context["paths.tool_dir"] = tool_str

        # Automatically alias all paths keys with and without 'paths.' prefix
        for k, v in merged_config.get("paths", {}).items():
            if isinstance(v, (str, int, float, bool)):
                context[k] = str(v)
                context[f"paths.{k}"] = str(v)

        expanded = expand_tokens(merged_config, context)
        if expanded == merged_config:
            break
        merged_config = expanded

    # 5. Convert paths section entries to absolute Path objects
    paths_dict = merged_config.get("paths", {})
    resolved_paths: Dict[str, Path] = {}
    for key, val in paths_dict.items():
        if isinstance(val, (str, Path)):
            p = Path(val)
            resolved_paths[key] = (
                p.resolve() if p.is_absolute() else (WORKSPACE_DIR / p).resolve()
            )
        else:
            resolved_paths[key] = val

    resolved_paths["workspace_dir"] = WORKSPACE_DIR
    resolved_paths["tool_dir"] = TOOL_DIR

    # Canonical .venv directory
    venv_dir = resolved_paths.get("venv_dir", WORKSPACE_DIR / ".venv")
    if not isinstance(venv_dir, Path):
        venv_dir = Path(venv_dir).resolve()
    venv_bin_dir = venv_dir / ("Scripts" if IS_WINDOWS else "bin")
    resolved_paths["venv_dir"] = venv_dir
    resolved_paths["venv_bin_dir"] = venv_bin_dir
    merged_config["paths"] = resolved_paths

    # 6. OS-specific environment & activation
    if IS_WINDOWS:
        venv_activate_cmd = f'call "{venv_bin_dir / "activate.bat"}"'
    else:
        venv_activate_cmd = f'source "{venv_bin_dir / "activate"}"'

    execution_env = os.environ.copy()
    if venv_bin_dir.exists():
        execution_env["PATH"] = (
            f"{venv_bin_dir}{os.pathsep}{execution_env.get('PATH', '')}"
        )
        execution_env["VIRTUAL_ENV"] = str(venv_dir)

    execution_env["PYTHONIOENCODING"] = "utf-8"
    execution_env["PYTHONUTF8"] = "1"

    merged_config["env"] = execution_env
    merged_config["venv_activate_cmd"] = venv_activate_cmd

    return ConfigNode(merged_config)


CONFIG = load_config()
