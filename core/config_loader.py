import os
import platform
from pathlib import Path
from typing import Any, Dict, List
import yaml

IS_WINDOWS = platform.system() == "Windows"
TOOL_DIR = Path(__file__).resolve().parent.parent

def find_workspace_root() -> Path:
    """Detect workspace root by looking upward from CWD for project markers."""
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
    # 1. Load default base config
    default_cfg_path = TOOL_DIR / "default_config.yaml"
    base_data: Dict[str, Any] = {}
    if default_cfg_path.exists():
        with default_cfg_path.open("r", encoding="utf-8") as f:
            base_data = yaml.safe_load(f) or {}

    # 2. Load root workspace config
    root_cfg_path = WORKSPACE_DIR / "config_tasks.yaml"
    if not root_cfg_path.exists():
        root_cfg_path = WORKSPACE_DIR / "config.yaml"

    root_data: Dict[str, Any] = {}
    if root_cfg_path.exists():
        with root_cfg_path.open("r", encoding="utf-8") as f:
            root_data = yaml.safe_load(f) or {}

    merged_config = deep_merge(base_data, root_data)

    # 3. Discover and merge module-level config_tasks.yaml files (e.g. embedded_system/)
    for sub_config_path in WORKSPACE_DIR.glob("*/config_tasks.yaml"):
        # Skip root config already loaded
        if sub_config_path.resolve() == root_cfg_path.resolve():
            continue
        with sub_config_path.open("r", encoding="utf-8") as f:
            sub_data = yaml.safe_load(f) or {}
            merged_config = deep_merge(merged_config, sub_data)

    # 4. Context for placeholder expansion
    context = {
        "workspace_dir": str(WORKSPACE_DIR),
        "tool_dir": str(TOOL_DIR),
    }
    for k, v in merged_config.get("paths", {}).items():
        if isinstance(v, str):
            context[k] = _expand_placeholders(v, context)

    # 5. Expand placeholders across all sections
    expanded = _expand_placeholders(merged_config, context)

    # 6. Convert 'paths' section entries to Path instances
    paths_section = _resolve_paths(expanded.get("paths", {}))
    paths_section["workspace_dir"] = WORKSPACE_DIR
    paths_section["tool_dir"] = TOOL_DIR

    venv_dir = paths_section.get("venv_dir", WORKSPACE_DIR / ".venv")
    venv_bin_dir = venv_dir / ("Scripts" if IS_WINDOWS else "bin")
    paths_section["venv_bin_dir"] = venv_bin_dir
    expanded["paths"] = paths_section

    # 7. Environment & Activation commands
    if IS_WINDOWS:
        venv_activate_cmd = f'call "{venv_bin_dir / "activate.bat"}"'
    else:
        venv_activate_cmd = f'source "{venv_bin_dir / "activate"}"'

    execution_env = os.environ.copy()
    if venv_bin_dir.exists():
        execution_env["PATH"] = f"{venv_bin_dir}{os.pathsep}{execution_env.get('PATH', '')}"
        execution_env["VIRTUAL_ENV"] = str(venv_dir)

    expanded["env"] = execution_env
    expanded["venv_activate_cmd"] = venv_activate_cmd

    return ConfigNode(expanded)

CONFIG = load_config()