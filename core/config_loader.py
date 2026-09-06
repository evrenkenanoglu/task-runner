import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict
import yaml

IS_WINDOWS = platform.system() == "Windows"
TOOL_DIR = Path(__file__).resolve().parent.parent

# Force parent Python process streams to UTF-8 on Windows
if IS_WINDOWS:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

def find_workspace_root() -> Path:
    cwd = Path.cwd().resolve()
    for directory in [cwd, *cwd.parents]:
        if (
            (directory / "config_tasks.yaml").exists()
            or (directory / "config.yaml").exists()
            or (directory / "tasks.py").exists()
            or (directory / ".git").exists()
        ):
            return directory
    return cwd

WORKSPACE_DIR = find_workspace_root()

class ConfigNode(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            val = self[name]
            if isinstance(val, dict) and not isinstance(val, ConfigNode):
                return ConfigNode(val)
            return val
        except KeyError:
            raise AttributeError(f"Configuration key '{name}' not found.")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = base.copy()
    for key, val in override.items():
        if isinstance(val, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged

def _expand_placeholders(val: Any, context: Dict[str, str]) -> Any:
    if isinstance(val, str):
        for _ in range(3):
            try:
                val = val.format(**context)
            except KeyError:
                break
        return val
    elif isinstance(val, dict):
        return {k: _expand_placeholders(v, context) for k, v in val.items()}
    elif isinstance(val, list):
        return [_expand_placeholders(item, context) for item in val]
    return val

def _resolve_paths(paths_dict: Dict[str, Any]) -> Dict[str, Path]:
    resolved = {}
    for key, val in paths_dict.items():
        if isinstance(val, str):
            p = Path(val)
            resolved[key] = p.resolve() if p.is_absolute() else (WORKSPACE_DIR / p).resolve()
        elif isinstance(val, Path):
            resolved[key] = val.resolve()
        else:
            resolved[key] = val
    return resolved

def load_config() -> ConfigNode:
    default_cfg_path = TOOL_DIR / "default_config.yaml"
    base_data: Dict[str, Any] = {}
    if default_cfg_path.exists():
        with default_cfg_path.open("r", encoding="utf-8") as f:
            base_data = yaml.safe_load(f) or {}

    root_cfg_path = WORKSPACE_DIR / "config_tasks.yaml"
    if not root_cfg_path.exists():
        root_cfg_path = WORKSPACE_DIR / "config.yaml"

    root_data: Dict[str, Any] = {}
    if root_cfg_path.exists():
        with root_cfg_path.open("r", encoding="utf-8") as f:
            root_data = yaml.safe_load(f) or {}

    merged_config = deep_merge(base_data, root_data)

    for sub_config_path in WORKSPACE_DIR.glob("*/config_tasks.yaml"):
        if sub_config_path.resolve() == root_cfg_path.resolve():
            continue
        with sub_config_path.open("r", encoding="utf-8") as f:
            sub_data = yaml.safe_load(f) or {}
            merged_config = deep_merge(merged_config, sub_data)

    context = {
        "workspace_dir": str(WORKSPACE_DIR),
        "tool_dir": str(TOOL_DIR),
    }
    for k, v in merged_config.get("paths", {}).items():
        if isinstance(v, str):
            context[k] = _expand_placeholders(v, context)

    expanded = _expand_placeholders(merged_config, context)

    paths_section = _resolve_paths(expanded.get("paths", {}))
    paths_section["workspace_dir"] = WORKSPACE_DIR
    paths_section["tool_dir"] = TOOL_DIR

    venv_dir = paths_section.get("venv_dir", WORKSPACE_DIR / ".venv")
    venv_bin_dir = venv_dir / ("Scripts" if IS_WINDOWS else "bin")
    paths_section["venv_bin_dir"] = venv_bin_dir
    expanded["paths"] = paths_section

    if IS_WINDOWS:
        venv_activate_cmd = f'call "{venv_bin_dir / "activate.bat"}"'
    else:
        venv_activate_cmd = f'source "{venv_bin_dir / "activate"}"'

    execution_env = os.environ.copy()
    if venv_bin_dir.exists():
        execution_env["PATH"] = f"{venv_bin_dir}{os.pathsep}{execution_env.get('PATH', '')}"
        execution_env["VIRTUAL_ENV"] = str(venv_dir)

    execution_env["PYTHONIOENCODING"] = "utf-8"
    execution_env["PYTHONUTF8"] = "1"

    expanded["env"] = execution_env
    expanded["venv_activate_cmd"] = venv_activate_cmd

    return ConfigNode(expanded)

CONFIG = load_config()