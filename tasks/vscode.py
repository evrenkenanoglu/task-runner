import inspect
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from invoke import Collection, Context, task
from core import WORKSPACE_DIR

IGNORED_PARAMS = {"c", "ctx", "opts", "extra"}

def _format_label(task_name: str) -> str:
    """Format 'es.esp32.chip-info' into 'ES: ESP32 Chip Info'."""
    parts = task_name.split(".")
    formatted_parts = []
    for part in parts:
        words = part.replace("_", " ").replace("-", " ").split()
        formatted_words = [
            w.upper() if len(w) <= 3 else w.capitalize() for w in words
        ]
        formatted_parts.append(" ".join(formatted_words))

    if len(formatted_parts) > 1:
        return f"{formatted_parts[0]}: {' '.join(formatted_parts[1:])}"
    return formatted_parts[0]

def _sanitize_id(name: str) -> str:
    """Convert a name to a valid VS Code input ID."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)

def _extract_task_inputs_and_args(
    task_name: str, t: Any
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Generate CLI args referencing VS Code inputs for non-boolean parameters."""
    if not t.body:
        return [task_name], []

    sig = inspect.signature(t.body)
    cli_args: List[str] = [task_name]
    inputs: List[Dict[str, Any]] = []

    task_help_dict = getattr(t, "help", {}) or {}
    task_prefix = _sanitize_id(task_name)

    for name, param in sig.parameters.items():
        if name in IGNORED_PARAMS:
            continue

        default = param.default

        # Boolean flags are toggle switches in Invoke (e.g. --dry-run), not key-value pairs
        if isinstance(default, bool):
            continue

        cli_flag = name.replace("_", "-")
        input_id = f"{task_prefix}_{name}"
        help_desc = task_help_dict.get(name, f"Value for --{cli_flag}")

        default_val = ""
        if default is not inspect.Parameter.empty and default is not None:
            default_val = str(default)

        inputs.append({
            "id": input_id,
            "type": "promptString",
            "description": f"{help_desc} (--{cli_flag})",
            "default": default_val,
        })
        cli_args.append(f"--{cli_flag}=${{input:{input_id}}}")

    return cli_args, inputs

def _collect_tasks_and_inputs(
    collection: Collection, prefix: str = ""
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Recursively collect tasks and their corresponding VS Code inputs."""
    all_tasks = []
    all_inputs = []

    for name, t in collection.tasks.items():
        full_name = f"{prefix}.{name}" if prefix else name
        doc = (t.body.__doc__ or "").strip().split("\n")[0] if t.body else ""

        task_args, task_inputs = _extract_task_inputs_and_args(full_name, t)

        task_entry: Dict[str, Any] = {
            "label": _format_label(full_name),
            "type": "shell",
            "command": "inv",
            "args": task_args,
            "problemMatcher": [],
        }
        if doc:
            task_entry["detail"] = doc

        all_tasks.append(task_entry)
        all_inputs.extend(task_inputs)

    for col_name, sub_col in collection.collections.items():
        sub_prefix = f"{prefix}.{col_name}" if prefix else col_name
        sub_tasks, sub_inputs = _collect_tasks_and_inputs(sub_col, sub_prefix)
        all_tasks.extend(sub_tasks)
        all_inputs.extend(sub_inputs)

    return all_tasks, all_inputs

@task(
    help={
        "clean": "Overwrite .vscode/tasks.json completely instead of merging",
    }
)
def sync(c: Context, clean: bool = False) -> None:
    """Auto-generate .vscode/tasks.json with interactive task inputs."""
    from tasks import ns

    vscode_dir = WORKSPACE_DIR / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    tasks_json_path = vscode_dir / "tasks.json"

    generated_tasks, generated_inputs = _collect_tasks_and_inputs(ns)
    generated_tasks.sort(key=lambda t: t["label"])
    generated_inputs.sort(key=lambda i: i["id"])

    existing_data: Dict[str, Any] = {"version": "2.0.0", "tasks": [], "inputs": []}

    if tasks_json_path.exists() and not clean:
        try:
            with tasks_json_path.open("r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            existing_data = {"version": "2.0.0", "tasks": [], "inputs": []}

    non_invoke_tasks = [
        t for t in existing_data.get("tasks", [])
        if t.get("command") != "inv"
    ]

    existing_non_invoke_inputs = [
        inp for inp in existing_data.get("inputs", [])
        if not any(inp.get("id") == gen_inp["id"] for gen_inp in generated_inputs)
    ]

    existing_data["tasks"] = non_invoke_tasks + generated_tasks
    existing_data["inputs"] = existing_non_invoke_inputs + generated_inputs

    with tasks_json_path.open("w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2)

    print(f"Synced {len(generated_tasks)} tasks and {len(generated_inputs)} inputs to {tasks_json_path}")