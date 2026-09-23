# ==============================================================================
# Task-Runner Smoke Test & Verification Suite
# Domain: Dynamic Task Discovery & Automated --dry-run Validation
# ==============================================================================

import time
from typing import List, Tuple
from invoke import Collection, Context, task


def _collect_task_names(collection: Collection, prefix: str = "") -> List[str]:
    """Recursively collects all task names from the Invoke namespace hierarchy."""
    task_names = []
    for name in collection.tasks.keys():
        full_name = f"{prefix}.{name}" if prefix else name
        task_names.append(full_name)

    for col_name, sub_col in collection.collections.items():
        sub_prefix = f"{prefix}.{col_name}" if prefix else col_name
        task_names.extend(_collect_task_names(sub_col, sub_prefix))

    return task_names


@task(
    name="dry-run",
    default=True,
    help={
        "exclude": "Comma-separated task names or substrings to skip (e.g. 'clean,erase')",
        "stop_on_fail": "Abort test execution immediately on the first task failure",
    },
)
def dry_run_all(c: Context, exclude: str = "", stop_on_fail: bool = False) -> None:
    """Discover all Invoke tasks in the workspace and execute them with --dry-run."""
    from tasks import ns

    all_tasks = _collect_task_names(ns)

    # Exclude self and tasks without --dry-run support to prevent false failures or recursion
    excluded_patterns = [
        "test.dry-run",
        "test",
        "vscode.sync",
        "deps.compile",
        "deps.install",
        "venv.clean",
        "venv.compile",
        "venv.create",
        "venv.install",
        "venv.setup",
    ]
    if exclude and str(exclude).strip():
        excluded_patterns.extend([e.strip() for e in exclude.split(",") if e.strip()])

    results: List[Tuple[str, str, float, str]] = []
    print(
        f"\n🔍 Discovered {len(all_tasks)} total tasks. Running dry-run smoke tests...\n"
    )

    for task_name in all_tasks:
        if any(
            pattern == task_name or (pattern in task_name and len(pattern) > 4)
            for pattern in excluded_patterns
        ):
            results.append((task_name, "SKIPPED", 0.0, "Excluded / Non-dryrun"))
            continue

        cmd = f"inv {task_name} --dry-run"
        start_time = time.perf_counter()

        res = c.run(cmd, warn=True, pty=False, hide=True)
        elapsed = time.perf_counter() - start_time

        if res.ok:
            results.append((task_name, "PASSED", elapsed, ""))
            print(f"  ✅ {task_name:<44} [{elapsed:.2f}s]")
        else:
            err_line = (
                (res.stderr or res.stdout or "Command returned non-zero exit code")
                .strip()
                .split("\n")[-1]
            )
            results.append((task_name, "FAILED", elapsed, err_line))
            print(f"  ❌ {task_name:<44} [{elapsed:.2f}s] -> {err_line}")
            if stop_on_fail:
                break

    # Summary Table Output
    col_w = 46
    print("\n" + "=" * 82)
    print(f"{'TASK NAME':<{col_w}} {'STATUS':<10} {'TIME':<10} {'DETAILS'}")
    print("=" * 82)

    passed = sum(1 for _, st, _, _ in results if st == "PASSED")
    failed = sum(1 for _, st, _, _ in results if st == "FAILED")
    skipped = sum(1 for _, st, _, _ in results if st == "SKIPPED")

    for name, status, duration, details in results:
        short_details = (details[:20] + "..") if len(details) > 22 else details
        print(f"{name:<{col_w}} {status:<10} {duration:>6.2f}s    {short_details}")

    print("=" * 82)
    print(
        f"Summary: {passed} Passed, {failed} Failed, {skipped} Skipped (Total: {len(results)})"
    )
    print("=" * 82 + "\n")

    if failed > 0:
        raise SystemExit(1)
