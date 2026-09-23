import importlib.util
from pathlib import Path
import sys
from invoke import Collection

# 1. Resolve TOOL_DIR and inject into sys.path before importing internal packages
TOOL_DIR = Path(__file__).resolve().parent.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

# 2. Internal imports
from core.config_loader import CONFIG, WORKSPACE_DIR

# Ensure workspace root is also in sys.path
if WORKSPACE_DIR.exists() and str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

# Directories to ignore during auto-discovery
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


def register_directory(
    tasks_dir: Path, collection: Collection, prefix: str = ""
) -> None:
    """Recursively discover and load task modules from a directory."""
    if not tasks_dir.exists():
        return

    for path in tasks_dir.rglob("*.py"):
        if path.name.startswith("__"):
            continue

        relative_path = path.relative_to(tasks_dir).with_suffix("")
        parts = [p.lower() for p in relative_path.parts]

        # Avoid redundant nesting if module name matches parent folder
        if len(parts) > 1 and parts[-1] == parts[-2]:
            parts = parts[:-1]

        module_name = f"dyn_{prefix}_{'_'.join(parts)}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"[Warning] Failed to load {path}: {e}")
            continue

        current_col = collection
        for part in parts[:-1]:
            if part not in current_col.collections:
                current_col.add_collection(Collection(part))
            current_col = current_col.collections[part]

        try:
            sub_col = Collection.from_module(module, name=parts[-1])
            if sub_col.tasks or sub_col.collections:
                current_col.add_collection(sub_col)
        except ValueError:
            pass


# ----------------------------------------------------------------------
# 1. Built-in Tool Tasks (e.g. task-runner/tasks/venv.py)
# ----------------------------------------------------------------------
register_directory(TOOL_DIR / "tasks", ns, prefix="tool")

# ----------------------------------------------------------------------
# 2. Workspace Root Tasks (WORKSPACE_ROOT/Tasks/ or tasks/)
# ----------------------------------------------------------------------
for name in ["Tasks", "tasks"]:
    root_tasks = WORKSPACE_DIR / name
    if root_tasks.exists() and root_tasks.resolve() != (TOOL_DIR / "tasks").resolve():
        register_directory(root_tasks, ns, prefix="root")
        break

# ----------------------------------------------------------------------
# 3. Dynamic Subproject Discovery (e.g. <subfolder>/Tasks/)
# ----------------------------------------------------------------------
aliases = CONFIG.get("task_namespaces", {})

for item in WORKSPACE_DIR.iterdir():
    if (
        not item.is_dir()
        or item.name in IGNORE_DIRS
        or item.resolve() == TOOL_DIR.resolve()
    ):
        continue

    for tasks_folder_name in ["Tasks", "tasks"]:
        candidate = item / tasks_folder_name
        if candidate.exists() and candidate.is_dir():
            namespace = aliases.get(item.name, item.name).lower()
            sub_collection = Collection(namespace)
            register_directory(candidate, sub_collection, prefix=namespace)

            if sub_collection.tasks or sub_collection.collections:
                ns.add_collection(sub_collection)
            break
