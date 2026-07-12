import json
import subprocess
import sys
from pathlib import Path

EXEC_ENTRY = Path(__file__).resolve().parents[2] / "benchmarks" / "dagi_eval" / "_exec_entry.py"


def _run(code_dir, module, func, input_dir, out_json, extra=()):
    cmd = [sys.executable, str(EXEC_ENTRY), str(code_dir), module, func,
           str(input_dir), str(out_json), *extra]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return json.loads(Path(out_json).read_text(encoding="utf-8"))


def test_runs_entry_and_writes_result(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.py").write_text(
        "def run(input_dir):\n    return {'n': 2, 'dir': True}\n", encoding="utf-8")
    payload = _run(ws, "m", "run", tmp_path, tmp_path / "out.json")
    assert payload == {"ok": True, "result": {"n": 2, "dir": True}}


def test_timing_mode_reports_times(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.py").write_text(
        "def run(input_dir):\n    return {'n': 1}\n", encoding="utf-8")
    payload = _run(ws, "m", "run", tmp_path, tmp_path / "out.json", ("--timing", "3"))
    assert payload["ok"] is True
    assert len(payload["times"]) == 3
    assert all(t >= 0 for t in payload["times"])


def test_crashing_module_reports_error(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.py").write_text(
        "def run(input_dir):\n    raise ValueError('boom')\n", encoding="utf-8")
    payload = _run(ws, "m", "run", tmp_path, tmp_path / "out.json")
    assert payload["ok"] is False
    assert "boom" in payload["error"]
