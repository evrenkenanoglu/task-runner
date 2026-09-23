# ==============================================================================
# SSoT Parameter & Domain Configuration Resolver
# Domain: Recursive base_config inheritance and dynamic {token} expansion
# Master SSoT Reference: configs/config_project.yaml
# ==============================================================================

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union
import yaml


class ConfigNode(dict):
    """Allows attribute-style dot notation access on configuration dictionaries."""

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
    """Recursively merges override dictionary into base dictionary."""
    merged = base.copy()
    for key, val in override.items():
        if isinstance(val, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def flatten_dict(
    d: Dict[str, Any], parent_key: str = "", sep: str = "."
) -> Dict[str, str]:
    """Flattens nested dictionary into dot-separated key-value pairs."""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, (str, int, float, bool)):
            items.append((new_key, str(v)))
    return dict(items)


def expand_tokens(data: Any, context: Dict[str, str]) -> Any:
    """Recursively replaces {placeholder.key} tokens using the context dictionary."""
    if isinstance(data, dict):
        return {k: expand_tokens(v, context) for k, v in data.items()}
    elif isinstance(data, list):
        return [expand_tokens(item, context) for item in data]
    elif isinstance(data, str):
        pattern = re.compile(r"\{([\w\.]+)\}")
        matches = pattern.findall(data)
        for match in matches:
            if match in context:
                data = data.replace(f"{{{match}}}", str(context[match]))
        return data
    return data


def find_workspace_root(start_path: Path) -> Path:
    """Detects workspace root by inspecting parent directories for boundary markers."""
    curr = start_path.resolve()
    for parent in [curr, *curr.parents]:
        if (
            (parent / "CMakeLists.txt").exists()
            or (parent / "tasks.py").exists()
            or (parent / ".git").exists()
        ):
            return parent
    return curr


def resolve_config(
    config_path: Union[str, Path],
    workspace_root: Optional[Union[str, Path]] = None,
    max_passes: int = 5,
    return_node: bool = False,
) -> Union[ConfigNode, Dict[str, Any]]:
    """Loads a YAML config, resolves base_config inheritance, and recursively expands {tokens}."""
    cfg_file = Path(config_path).resolve()
    if not cfg_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {cfg_file}")

    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 1. Recursive base_config inheritance (e.g. config_project.yaml)
    base_file = cfg.get("base_config")
    if base_file:
        base_path = (cfg_file.parent / base_file).resolve()
        if base_path.exists():
            base_cfg = resolve_config(
                base_path,
                workspace_root=workspace_root,
                max_passes=max_passes,
                return_node=False,
            )
            cfg = deep_merge(base_cfg, cfg)

    # 2. Inject canonical workspace root context
    root = (
        Path(workspace_root).resolve()
        if workspace_root
        else find_workspace_root(cfg_file.parent)
    )
    root_str = str(root)

    paths_cfg = cfg.setdefault("paths", {})
    paths_cfg.setdefault("workspace_dir", root_str)

    # 3. Multi-pass token resolution
    for _ in range(max_passes):
        context = flatten_dict(cfg)
        context["workspace_dir"] = root_str
        context["project_root"] = root_str
        context["project_root_dir"] = root_str
        context["paths.workspace_dir"] = root_str

        expanded = expand_tokens(cfg, context)
        if expanded == cfg:
            break
        cfg = expanded

    return ConfigNode(cfg) if return_node else cfg


def resolve_to_file(
    config_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    workspace_root: Optional[Union[str, Path]] = None,
) -> Path:
    """Resolves config_*.yaml with SSoT inheritance and writes a flat, standalone YAML file for tools."""
    cfg_file = Path(config_path).resolve()
    resolved_data = resolve_config(
        cfg_file, workspace_root=workspace_root, return_node=False
    )

    root = (
        Path(workspace_root).resolve()
        if workspace_root
        else find_workspace_root(cfg_file.parent)
    )

    if output_path:
        out_file = Path(output_path).resolve()
    else:
        out_dir = root / "build" / "configs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{cfg_file.stem}.resolved.yaml"

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        yaml.dump(resolved_data, f, default_flow_style=False, sort_keys=False)

    return out_file
