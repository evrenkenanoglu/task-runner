import shutil
from pathlib import Path
from invoke import Context, task
from core import CONFIG, IS_WINDOWS, CommandSerializer

@task(
    help={
        "input_file": "Source requirements.in file",
        "output_file": "Destination compiled requirements.txt lockfile",
        "upgrade": "Re-resolve all dependencies to latest versions",
    }
)
def compile(
    c: Context,
    input_file: str = "requirements.in",
    output_file: str = "requirements.txt",
    upgrade: bool = False,
) -> None:
    """Compile requirements.in to requirements.txt using uv."""
    in_path = Path(input_file)
    if not in_path.is_absolute():
        in_path = CONFIG.paths.tool_dir / in_path

    out_path = Path(output_file)
    if not out_path.is_absolute():
        out_path = CONFIG.paths.tool_dir / out_path

    if not in_path.exists():
        raise FileNotFoundError(f"Source requirements file not found: {in_path}")

    upgrade_flag = "--upgrade" if upgrade else ""
    cmd = f'uv pip compile "{in_path}" -o "{out_path}" --annotation-style line {upgrade_flag}'.strip()

    serializer = CommandSerializer()
    serializer.add(cmd)
    serializer.run(c)

@task(
    help={
        "python_version": "Python version to provision via uv (e.g. 3.12, 3.13)",
        "clear": "Delete existing venv before creation",
    }
)
def create(
    c: Context,
    python_version: str = "",
    clear: bool = False,
) -> None:
    """Create a virtual environment using uv."""
    venv_dir = CONFIG.paths.venv_dir
    py_ver = python_version or CONFIG.get("python", {}).get("version", "")

    if clear and venv_dir.exists():
        shutil.rmtree(venv_dir)
        print(f"Removed existing virtual environment: {venv_dir}")

    py_flag = f"--python {py_ver}" if py_ver else ""
    cmd = f'uv venv "{venv_dir}" {py_flag}'.strip()

    serializer = CommandSerializer()
    serializer.add(cmd)
    serializer.run(c)

@task(
    help={
        "requirements": "Path to requirements.txt lockfile",
        "upgrade": "Upgrade installed packages",
    }
)
def install(
    c: Context,
    requirements: str = "",
    upgrade: bool = False,
) -> None:
    """Install dependencies into the virtual environment using uv pip."""
    req_file = Path(requirements) if requirements else CONFIG.paths.requirements_file
    if not req_file.exists():
        raise FileNotFoundError(f"Requirements lockfile not found: {req_file}")

    upgrade_flag = "--upgrade" if upgrade else ""
    python_bin = CONFIG.paths.venv_bin_dir / ("python.exe" if IS_WINDOWS else "python")
    cmd = f'uv pip install -r "{req_file}" --python "{python_bin}" {upgrade_flag}'.strip()

    serializer = CommandSerializer()
    serializer.add(cmd)
    serializer.run(c)

@task
def clean(c: Context) -> None:
    """Delete the virtual environment directory."""
    venv_dir = CONFIG.paths.venv_dir
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
        print(f"Removed virtual environment: {venv_dir}")
    else:
        print(f"Virtual environment does not exist: {venv_dir}")

@task(
    help={
        "python_version": "Python version to provision via uv",
        "requirements": "Path to requirements.txt lockfile",
    }
)
def setup(
    c: Context,
    python_version: str = "",
    requirements: str = "",
) -> None:
    """Wipe, recreate, and install all dependencies in a single step."""
    clean(c)
    create(c, python_version=python_version)
    install(c, requirements=requirements)