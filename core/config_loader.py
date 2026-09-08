import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List
import yaml

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

def find_workspace_root() -> Path:
    """Detect workspace root using project boundary markers (.git or tasks.py)."""
    cwd = Path.cwd().resolve()
    for directory in [cwd, *cwd.parents]:
        if (directory / "tasks.py").exists() or (directory / ".git").exists():
            return directory
        if (directory / "config_tasks.yaml").exists() or (directory / "config.yaml").exists():
            return directory
    return cwd

WORKSPACE_DIR = find_workspace_root()

class ConfigNode(dict):
    """Allows dot-notation attribute access on dictionary keys."""
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
    """Recursively merge override dictionary into base dictionary."""
    merged = base.copy()
    for key, val in override.items():
        if isinstance(val, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged

def _find_root_config() -> Path:
    """Find the root configuration file via environment variable or search paths."""
    env_override = os.environ.get("TASK_CONFIG_PATH")
    if env_override:
        custom_path = Path(env_override)
        return custom_path if custom_path.is_absolute() else (WORKSPACE_DIR / custom_path).resolve()

    candidates = [
        WORKSPACE_DIR / "config_tasks.yaml",
        WORKSPACE_DIR / "config.yaml",
        WORKSPACE_DIR / "configs" / "config_tasks.yaml",
        WORKSPACE_DIR / "configs" / "config.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return (WORKSPACE_DIR / "config_tasks.yaml").resolve()

def _expand_placeholders(val: Any, context: Dict[str, str]) -> Any:
    """Recursively expand {placeholder} strings."""
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
    """Convert all path strings into resolved pathlib.Path objects."""
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
    # 1. Base default configuration
    default_cfg_path = TOOL_DIR / "default_config.yaml"
    base_data: Dict[str, Any] = {}
    if default_cfg_path.exists():
        with default_cfg_path.open("r", encoding="utf-8") as f:
            base_data = yaml.safe_load(f) or {}

    # 2. Root project configuration
    root_cfg_path = _find_root_config()
    root_data: Dict[str, Any] = {}
    if root_cfg_path.exists():
        with root_cfg_path.open("r", encoding="utf-8") as f:
            root_data = yaml.safe_load(f) or {}

    merged_config = deep_merge(base_data, root_data)

    # 3. Recursive discovery of all sub-module config files
    discovered_sub_configs: List[Path] = []
    for pattern in ["**/config_tasks.yaml", "**/config.yaml"]:
        for path in WORKSPACE_DIR.glob(pattern):
            resolved_path = path.resolve()
            
            # Skip root config and tool directory
            if resolved_path == root_cfg_path:
                continue
            if TOOL_DIR.resolve() in resolved_path.parents:
                continue
            # Skip ignored directories (.git, .venv, build, etc.)
            if any(part in IGNORE_DIRS for part in resolved_path.parts):
                continue
            
            discovered_sub_configs.append(resolved_path)

    # Sort to maintain deterministic merge order
    discovered_sub_configs = sorted(list(set(discovered_sub_configs)), key=lambda p: len(p.parts))

    for sub_config_path in discovered_sub_configs:
        with sub_config_path.open("r", encoding="utf-8") as f:
            sub_data = yaml.safe_load(f) or {}
            merged_config = deep_merge(merged_config, sub_data)

    # 4. Interpolation context
    context = {
        "workspace_dir": str(WORKSPACE_DIR),
        "tool_dir": str(TOOL_DIR),
    }
    for k, v in merged_config.get("paths", {}).items():
        if isinstance(v, str):
            context[k] = _expand_placeholders(v, context)

    # 5. Expand placeholders across all sections
    expanded = _expand_placeholders(merged_config, context)

    # 6. Convert paths section entries to absolute Path objects
    paths_section = _resolve_paths(expanded.get("paths", {}))
    paths_section["workspace_dir"] = WORKSPACE_DIR
    paths_section["tool_dir"] = TOOL_DIR

    venv_dir = paths_section.get("venv_dir", WORKSPACE_DIR / ".venv")
    venv_bin_dir = venv_dir / ("Scripts" if IS_WINDOWS else "bin")
    paths_section["venv_bin_dir"] = venv_bin_dir
    expanded["paths"] = paths_section

    # 7. OS-specific environment & activation
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
