"""
scripts/monitor_tests.py — Run tests one-by-one (oldest file first), monitoring RAM.
Exits immediately if system RAM usage exceeds RAM_THRESHOLD_PCT.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

RAM_THRESHOLD_PCT = 70.0
POLL_INTERVAL = 0.25  # seconds

# Test files ordered from oldest git creation date to newest (untracked = newest).
ORDERED_FILES = [
    "tests/test_scope_tools.py",
    "tests/test_plan_parser.py",
    "tests/test_spawn_subagent_tool.py",
    "tests/test_continuation.py",
    "tests/test_config_loader.py",
    "tests/test_bash_tools.py",
    "tests/test_tool_filter.py",  # untracked — newest
]

PYTHON = sys.executable
REPO_ROOT = Path(__file__).parent.parent


def ram_pct() -> float:
    return psutil.virtual_memory().percent


def collect_node_ids(test_file: str) -> list[str]:
    """Ask pytest to list every node ID in *test_file* without running them."""
    result = subprocess.run(
        [PYTHON, "-m", "pytest", test_file, "--collect-only", "-q", "--no-header"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    ids = [
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith("=")
    ]
    return ids


def run_single_test(node_id: str) -> tuple[str, float, float, float]:
    """Run one test, polling RAM throughout. Returns (status, ram_before, ram_peak, ram_after)."""
    ram_before = ram_pct()
    peak: list[float] = [ram_before]
    killed: list[bool] = [False]

    proc = subprocess.Popen(
        [PYTHON, "-m", "pytest", node_id, "-v", "--no-header", "--tb=short"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=REPO_ROOT,
    )

    def _poll():
        while proc.poll() is None:
            current = ram_pct()
            if current > peak[0]:
                peak[0] = current
            if current > RAM_THRESHOLD_PCT:
                killed[0] = True
                proc.kill()
                return
            time.sleep(POLL_INTERVAL)

    monitor = threading.Thread(target=_poll, daemon=True)
    monitor.start()

    stdout, _ = proc.communicate()
    monitor.join(timeout=2.0)

    ram_after = ram_pct()

    if killed[0]:
        status = "KILLED"
    elif proc.returncode == 0:
        status = "PASSED"
    elif "ERROR" in (stdout or ""):
        status = "ERROR"
    else:
        status = "FAILED"

    return status, ram_before, peak[0], ram_after, stdout or ""


def main():
    total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    threshold_gb = total_ram_gb * RAM_THRESHOLD_PCT / 100
    print(f"\n{'='*70}")
    print(f"  RAM monitor — threshold: {RAM_THRESHOLD_PCT}%  "
          f"({threshold_gb:.1f} GB of {total_ram_gb:.1f} GB)")
    print(f"  Base RAM before any test: {ram_pct():.1f}%")
    print(f"{'='*70}\n")

    all_node_ids: list[tuple[str, str]] = []  # (file, node_id)
    for f in ORDERED_FILES:
        ids = collect_node_ids(f)
        for nid in ids:
            all_node_ids.append((f, nid))

    col = 60
    print(f"{'TEST':<{col}} {'STATUS':<8} {'BEFORE':>7} {'PEAK':>7} {'AFTER':>7}")
    print("-" * (col + 32))

    for file, node_id in all_node_ids:
        short = node_id.replace("tests/", "")
        status, before, peak, after, output = run_single_test(node_id)

        flag = " ◀ THRESHOLD EXCEEDED!" if status == "KILLED" else ""
        print(f"{short:<{col}} {status:<8} {before:>6.1f}% {peak:>6.1f}% {after:>6.1f}%{flag}")

        if status == "KILLED":
            print(f"\n!!! RAM exceeded {RAM_THRESHOLD_PCT}% during: {node_id}")
            print(f"    Peak recorded: {peak:.1f}%")
            print("\n--- stdout of offending test ---")
            print(output[-2000:] if len(output) > 2000 else output)
            sys.exit(1)

        if status in ("FAILED", "ERROR"):
            print(f"    ↳ stdout snippet:")
            for line in output.splitlines()[-15:]:
                print(f"      {line}")

    print(f"\n{'='*70}")
    print(f"  All {len(all_node_ids)} tests completed. Peak RAM never exceeded {RAM_THRESHOLD_PCT}%.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
