"""Subprocess entry executor for the dagi eval benchmark.

Usage:
    python _exec_entry.py <code_dir> <module> <func> <input_dir> <out_json> [--timing N]

Imports <module> from <code_dir>, calls <func>(input_dir), writes JSON to <out_json>:
    {"ok": true, "result": ...}                      (normal mode)
    {"ok": true, "result": ..., "times": [...]}      (timing: 1 warmup + N timed calls)
    {"ok": false, "error": "<traceback tail>"}       (any exception)

Runs as a plain script (not -m) so the parent can set cwd to a scratch dir.
"""
import importlib
import json
import sys
import time
import traceback


def main() -> None:
    code_dir, module_name, func_name, input_dir, out_json = sys.argv[1:6]
    timing_runs = 0
    if "--timing" in sys.argv:
        timing_runs = int(sys.argv[sys.argv.index("--timing") + 1])

    sys.path.insert(0, code_dir)
    try:
        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name)
        if timing_runs:
            func(input_dir)  # warmup
            times, result = [], None
            for _ in range(timing_runs):
                t0 = time.perf_counter()
                result = func(input_dir)
                times.append(time.perf_counter() - t0)
            payload = {"ok": True, "result": result, "times": times}
        else:
            payload = {"ok": True, "result": func(input_dir)}
    except BaseException:
        payload = {"ok": False, "error": traceback.format_exc()[-2000:]}

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f)


if __name__ == "__main__":
    main()
