"""
==============================================================================
Dynamic Task Discovery & Namespace Auto-Mounting Engine
==============================================================================
"""

import importlib.util
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any, Dict, List, Optional, Set
from invoke import Collection

DEFAULT_IGNORE_DIRS: Set[str] = {
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "__pycache__",
    ".idea",
    ".vscode",
}


def _slugify(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    s = re.sub(r"[_\s]+", "-", s)
    return s.lower().strip("-")


def _get_or_create_collection(parent: Collection, name: str) -> Collection:
    slug_name = _slugify(name)
    if slug_name in parent.collections:
        return parent.collections[slug_name]
    sub = Collection(slug_name)
    parent.add_collection(sub, name=slug_name)
    return sub


class TaskDiscovery:
    def __init__(self, ignore_dirs: Optional[Set[str]] = None) -> None:
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS

    def load_module(self, file_path: Path) -> Optional[ModuleType]:
        resolved = file_path.resolve()
        if not resolved.is_file():
            return None

        path_slug = re.sub(r"[^a-zA-Z0-9_]", "_", str(resolved))
        module_name = f"_discovered_task_{path_slug}"

        if module_name in sys.modules:
            return sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, resolved)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
            return module
        except Exception as err:
            sys.stderr.write(
                f"\033[33m⚠️  [DISCOVERY WARN] Skipping '{resolved}': {err}\033[0m\n"
            )
            sys.modules.pop(module_name, None)
            return None

    def mount_module(
        self, module: ModuleType, target_collection: Collection, name: str
    ) -> bool:
        slug_name = _slugify(name)
        try:
            col = Collection.from_module(module, name=slug_name)
        except Exception as err:
            sys.stderr.write(
                f"\033[33m⚠️  [DISCOVERY WARN] Could not mount '{name}': {err}\033[0m\n"
            )
            return False

        if col.tasks or col.collections:
            target_collection.add_collection(col, name=slug_name)
            return True
        return False

    def discover_tools(
        self,
        search_root: Path,
        root_col: Collection,
        namespace: str,
        task_filename: str,
    ) -> int:
        root_dir = search_root.resolve()
        if not root_dir.exists():
            return 0

        base_col = root_col
        if namespace:
            for part in namespace.split("."):
                base_col = _get_or_create_collection(base_col, part)

        mounted = 0
        for path in sorted(root_dir.rglob(task_filename)):
            resolved = path.resolve()
            if any(part in self.ignore_dirs for part in resolved.parts):
                continue

            tool_name = path.parent.name
            mod = self.load_module(resolved)
            if mod and self.mount_module(mod, base_col, tool_name):
                mounted += 1

        return mounted

    def discover_files(
        self, search_root: Path, root_col: Collection, namespace: str, pattern: str
    ) -> int:
        root_dir = search_root.resolve()
        if not root_dir.exists():
            return 0

        base_col = root_col
        if namespace:
            for part in namespace.split("."):
                base_col = _get_or_create_collection(base_col, part)

        mounted = 0
        for path in sorted(root_dir.glob(pattern)):
            resolved = path.resolve()
            if resolved.name.startswith("__") or resolved.name == "tasks.py":
                continue
            if any(part in self.ignore_dirs for part in resolved.parts):
                continue

            mod = self.load_module(resolved)
            if mod and self.mount_module(mod, base_col, resolved.stem):
                mounted += 1

        return mounted

    def discover_from_config(self, config: Any, root_collection: Collection) -> None:
        discovery_rules = (
            config.get("discovery", {}).get("tasks", [])
            if hasattr(config, "get")
            else []
        )
        for rule in discovery_rules:
            raw_path = rule.get("path")
            if not raw_path:
                continue

            path = Path(raw_path).resolve()
            ns = rule.get("namespace", "")
            mode = rule.get("mode", "flat")

            if mode in ("flat", "tree"):
                self.discover_tools(
                    path, root_collection, ns, rule.get("task_filename", "tasks.py")
                )
            else:
                self.discover_files(
                    path, root_collection, ns, rule.get("pattern", "*.py")
                )
