---
name: task-runner-engine-architect
description: Authoritative architectural specification and engineering guidelines for maintaining, extending, and debugging the generic Tools/task-runner framework. Covers recursive config merging, multi-pass token resolution, dynamic AST task discovery, cross-platform process serialization, and the engine error post-mortem registry.
version: 2.0.0
target_runtime: Python 3.13 / uv / invoke
target_directory: Tools/task-runner/
triggers:
  - "modify task-runner"
  - "update config_loader"
  - "update config_resolver"
  - "update task discovery"
  - "add built-in task"
  - "fix task runner engine"
---

# Skill: Task-Runner Engine Architecture & Maintenance

## 1. Engine Mission & Strict Separation Boundaries

`Tools/task-runner/` is an **independent, reusable orchestration engine**. It is completely decoupled from any specific project, chip, or domain.

### ❌ Invariant Prohibitions (Never Violate):
1. **Zero Domain Knowledge:** The engine must **never** contain hardcoded references to `"embedded_system"`, `"esp32"`, `"matter"`, or any specific hardware target.
2. **Zero Project-Specific Paths:** Paths must always be derived dynamically from `find_workspace_root()`, `TOOL_DIR`, or tokens defined in `CONFIG`.
3. **No Unsafe Module Clobbering:** When loading external `tasks.py` files dynamically, never import them under generic names like `"tasks"`. Always generate a unique path-derived slug in `sys.modules`.

---

## 2. Engine Component Architecture

```
Tools/task-runner/
├── core/
│   ├── config_loader.py        # SSoT discovery, sub-config merging, CONFIG singleton
│   ├── config_resolver.py      # Recursive base_config, {tokens}, {config_dir}, resolve_to_file
│   ├── serializer.py           # CommandSerializer (UTF-8, PTY, execution logging)
│   └── discovery.py            # AST/Module loader, flat tool namespace builder
├── tasks/
│   ├── __init__.py             # Master Collection assembler (loads built-ins + discovered)
│   ├── test.py                 # Smoke-test suite (inv test.dry-run across all discovered tasks)
│   ├── venv.py                 # uv-based virtualenv manager (compile, install, clean, setup)
│   └── vscode.py               # Auto-generator for .vscode/tasks.json from Invoke AST
├── default_config.yaml         # Engine fallback defaults (paths, python version)
├── pyproject.toml              # Engine package definition
├── requirements.in             # Direct engine dependencies (invoke, pyyaml, uv)
└── requirements.txt            # Lockfile compiled via uv
```

---

## 3. Subsystem Specifications

### A. Configuration & Token Engine (`config_loader.py` & `config_resolver.py`)

1. **Workspace Root Detection:**
   `find_workspace_root()` traverses parent directories looking for boundary markers: `CMakeLists.txt`, `tasks.py`, or `.git`.
2. **The 3-Step Merge Pipeline:**
   - **Step 1:** Load `default_config.yaml` from `TOOL_DIR`.
   - **Step 2:** Load root `configs/config_tasks.yaml` (or path in `TASK_CONFIG_PATH`).
   - **Step 3 (Submodule Globs):** Globs `**/config_tasks.yaml` across `WORKSPACE_DIR` (skipping `IGNORE_DIRS` and `TOOL_DIR`) and recursively calls `deep_merge()`.
3. **Multi-Pass Token Expansion:**
   Runs up to 5 passes over the merged dictionary. Automatically injects:
   - `{workspace_dir}`: Root of the repository.
   - `{tool_dir}`: Path to `Tools/task-runner`.
   - `{config_dir}`: The exact directory of the specific `config_tasks.yaml` currently being parsed.

---

### B. Dynamic Task Discovery (`tasks/__init__.py`)

Task discovery operates without hardcoded task names using a 3-tier convention:

1. **Tier 1 (Built-ins):** Discovers all `.py` files inside `TOOL_DIR / "tasks"` $\rightarrow$ mounted under `ns` directly (`venv`, `vscode`, `test`).
2. **Tier 2 (Domain Tasks):** Scans `<subfolder>/Tasks/*.py` using aliases in `task_namespaces` (e.g. `embedded_system` $\rightarrow$ `inv es.<domain>.<task>`).
3. **Tier 3 (Tool Tasks):** Recursively finds `<subfolder>/Tools/**/tasks.py`.
   - **The Flat Mounting Rule:** It extracts the tool's immediate folder name (`AI_Assistant_Runner`), slugifies it (`ai-assistant-runner`), and mounts it directly under `tools.<tool-name>.*`. Intermediate folder depth (`AI/`, `UTILS/`) is stripped to guarantee stable CLI task names.

---

### C. Execution & Stream Serializer (`core/serializer.py`)

- **PTY Management:** Automatically defaults `pty = True` on Linux/macOS/WSL and `pty = False` on Windows.
- **Stream Encoding:** Enforces UTF-8 reconfiguration on Windows for standard streams (`sys.stdout.reconfigure(encoding="utf-8")`).
- **Command Prefixing:** Prepend `CONFIG.venv_activate_cmd` to guarantee child process execution inside the project's virtual environment.

---

## 4. Engine Post-Mortem & Error Registry (Crucial for AI Self-Correction)

When modifying or debugging `Tools/task-runner`, consult this failure registry:

### Incident E1: Module Overwrite Collision during Dynamic Import
- **Symptom:** Discovered tasks execute the wrong code or only the last discovered tool's tasks appear.
- **Root Cause:** Using a static name like `importlib.util.spec_from_file_location("tasks", path)` overwrites `sys.modules["tasks"]` for every tool in the workspace.
- **Engine Invariant:**
  ```python
  path_slug = re.sub(r"[^a-zA-Z0-9_]", "_", str(path.resolve()))
  module_name = f"dyn_discovered_{path_slug}"
  ```
  Every dynamically loaded file must have a unique, deterministic slug in `sys.modules`.

---

### Incident E2: Invoke Reserved `--config` Argument Collision
- **Symptom:**
  ```text
  AttributeError: No attribute or config key found for '_load_'
  invoke.exceptions.UnknownFileType: Config files of type '' (from file '') are not supported!
  ```
- **Root Cause:** Invoke has a global CLI flag: `-f, --config=STRING`. When an Invoke task defines a parameter named `config` and an empty string `--config=` is passed (e.g. from VS Code), Invoke intercepts it as its own config file, fails to detect the extension on `""`, and crashes before running task code.
- **Engine Invariant:**
  - In `tasks/vscode.py`: Never generate `--config` for task parameters.
  - In all tasks: Name configuration arguments `config_path` or `cfg`, never `config`.

---

### Incident E3: Path-Dependent CLI Name Fragility
- **Symptom:** Moving `Tools/AI_Assistant_Runner` into `Tools/AI/AI_Assistant_Runner` broke CLI scripts and CI with `No idea what 'tools.ai-assistant-runner' is!`.
- **Root Cause:** Discoverer used relative path parts (`['ai', 'ai_assistant_runner']`), generating nested collections (`tools.ai.ai-assistant-runner`) that changed whenever folders were rearranged.
- **Engine Invariant:** Tool discovery must be **flat under `tools`**. Use `path.parent.name` or explicit `TOOL_NAME` attribute in the target module. Do not mirror folder depth in the CLI namespace.

---

### Incident E4: Submodule Path Double-Nesting in Standalone Mode
- **Symptom:**
  ```text
  FileNotFoundError: .../embedded_system/embedded_system/Tasks
  ```
- **Root Cause:** A submodule's `config_tasks.yaml` used `{workspace_dir}/embedded_system`. When running standalone inside `embedded_system/`, `{workspace_dir}` was already `embedded_system`.
- **Engine Invariant:** In `core/config_resolver.py`, always inject `{config_dir}` during multi-pass expansion. Subsystems anchor to `{config_dir}` so they resolve identically whether running in root or standalone.

---

### Incident E5: Missing Python Binary in POSIX Subshells
- **Symptom:**
  ```text
  /bin/bash: line 1: python: command not found (exit code 127)
  ```
- **Root Cause:** Modern Ubuntu/Debian/WSL installs have `python3`, not `python`. Calling `python` directly in a raw subshell fails if `python-is-python3` is not installed.
- **Engine Invariant:** Always use `sys.executable` when constructing subcommands to guarantee using the active virtual environment's Python binary.

---

## 5. Verification Protocol for Engine Changes

Whenever modifying any file inside `Tools/task-runner/`:

1. **Verify No Built-In Breakages:**
   ```bash
   inv --list
   ```
   *(Must list `test.dry-run`, `venv.*`, `vscode.sync`, `es.*`, and `tools.*` without warnings).*

2. **Run Dry-Run Smoke Test:**
   ```bash
   inv test.dry-run
   ```
   *(Must recursively discover all tasks across the workspace and execute `--dry-run` successfully).*

3. **Verify VS Code Sync Generation:**
   ```bash
   inv vscode.sync
   ```
   *(Must parse AST signatures and update `.vscode/tasks.json` with zero JSON schema errors).*

4. **Verify Dependency Compilation:**
   ```bash
   inv venv.compile
   ```
   *(Must compile `requirements.in` to `requirements.txt` via `uv` without errors).*

## Error Registry Maintenance

Before engine work, review Section 4's incident registry. Record each verified, reusable mistake discovered during the task there before considering the work complete, including symptom, root cause, and prevention. Do not record speculation, transient output, or secrets.