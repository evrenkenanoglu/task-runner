import importlib.util
from pathlib import Path
import re
import sys
from invoke import Collection

# 1. Resolve TOOL_DIR and inject into sys.path
TOOL_DIR = Path(__file__).resolve().parent.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

# 2. Internal imports
from core.config_loader import CONFIG, WORKSPACE_DIR

if WORKSPACE_DIR.exists() and str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

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

ns = Collection()


def _slugify(name: str) -> str:
    """Normalize PascalCase, camelCase, and snake_case to canonical kebab-case."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    s = re.sub(r"[_\s]+", "-", s)
    return s.lower().strip("-")


def register_tasks_dir(
    tasks_dir: Path, collection: Collection, prefix: str = ""
) -> None:
    """Discovers standalone task files (e.g. *.py in embedded_system/Tasks/)."""
    if not tasks_dir.exists():
        return

    for path in tasks_dir.glob("*.py"):
        if path.name.startswith("__") or path.name == "tasks.py":
            continue

        module_name = f"dyn_{prefix}_{path.stem.lower()}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue

        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            sub_col = Collection.from_module(mod, name=_slugify(path.stem))
            if sub_col.tasks or sub_col.collections:
                collection.add_collection(sub_col)
        except Exception as e:
            print(f"[Warning] Failed to load {path}: {e}")


def register_tools_dir(tools_root: Path, tools_collection: Collection) -> None:
    """Recursively finds all 'tasks.py' files and mounts them FLAT under tools.<tool-name>.

    Moving a tool inside Tools/ (e.g. Tools/AI/Tool or Tools/Tool) will NEVER change
    its command name!
    """
    if not tools_root.exists():
        return

    for path in sorted(tools_root.rglob("tasks.py")):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue

        # Load module safely
        slug_path = re.sub(r"[^a-zA-Z0-9_]", "_", str(path.resolve()))
        module_name = f"dyn_tool_{slug_path}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue

        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            print(f"[Warning] Failed to load tool tasks from {path}: {e}")
            continue

        # Stable Identity: Check if tasks.py declares explicit TOOL_NAME,
        # otherwise fallback to the tool's immediate folder name.
        explicit_name = getattr(mod, "TOOL_NAME", None)
        raw_name = explicit_name or path.parent.name
        tool_slug = _slugify(raw_name)

        try:
            sub_col = Collection.from_module(mod, name=tool_slug)
            if sub_col.tasks or sub_col.collections:
                tools_collection.add_collection(sub_col, name=tool_slug)
        except Exception as e:
            print(f"[Warning] Could not mount {tool_slug}: {e}")


# ----------------------------------------------------------------------
# 1. Built-in Task-Runner Tasks (test, venv, vscode)
# ----------------------------------------------------------------------
register_tasks_dir(TOOL_DIR / "tasks", ns, prefix="builtin")

# ----------------------------------------------------------------------
# 2. Workspace Root Tasks (WORKSPACE_ROOT/Tasks/ or tasks/)
# ----------------------------------------------------------------------
for name in ["Tasks", "tasks"]:
    root_tasks = WORKSPACE_DIR / name
    if root_tasks.exists() and root_tasks.resolve() != (TOOL_DIR / "tasks").resolve():
        register_tasks_dir(root_tasks, ns, prefix="root")
        break

# ----------------------------------------------------------------------
# 3. Dynamic Subproject Discovery
# ----------------------------------------------------------------------
aliases = CONFIG.get("task_namespaces", {})

for item in WORKSPACE_DIR.iterdir():
    if (
        not item.is_dir()
        or item.name in IGNORE_DIRS
        or item.resolve() == TOOL_DIR.resolve()
    ):
        continue

    # A. Domain Tasks (e.g. embedded_system/Tasks/*.py -> inv es.<domain>.<task>)
    for tasks_folder in ["Tasks", "tasks"]:
        cand = item / tasks_folder
        if cand.exists() and cand.is_dir():
            ns_name = aliases.get(item.name, item.name).lower()
            if ns_name not in ns.collections:
                ns.add_collection(Collection(ns_name))
            register_tasks_dir(cand, ns.collections[ns_name], prefix=ns_name)
            break

    # B. Tools Tasks (e.g. embedded_system/Tools/**/tasks.py -> inv tools.<tool-name>.<task>)
    for tools_folder in ["Tools", "tools"]:
        cand_tools = item / tools_folder
        if cand_tools.exists() and cand_tools.is_dir():
            if "tools" not in ns.collections:
                ns.add_collection(Collection("tools"))
            register_tools_dir(cand_tools, ns.collections["tools"])
            break
