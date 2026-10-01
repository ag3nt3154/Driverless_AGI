"""Tests for the read_large_file tool (.dagi/subagents/read-large-file/main.py)."""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent import DAGI_ROOT
from agent.base_tool import BaseTool

SUBAGENTS_DIR = DAGI_ROOT / ".dagi" / "subagents"


def _load_tool_class() -> type:
    """Import main.py and return the BaseTool subclass."""
    main_py = SUBAGENTS_DIR / "read-large-file" / "main.py"
    mod_name = "_dagi_subagent_read_large_file"
    dagi_str = str(DAGI_ROOT)
    if dagi_str not in sys.path:
        sys.path.insert(0, dagi_str)
    spec = importlib.util.spec_from_file_location(mod_name, main_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseTool) and obj is not BaseTool:
            return obj
    raise RuntimeError(f"No BaseTool subclass in {main_py}")


def _make_tool(tmp_path: Path, *, model: str = "main-model", worker: str | None = "worker-model"):
    config = SimpleNamespace(
        project_path=tmp_path,
        sandbox_mode=False,
        services={},
        reserve_tokens=16_384,
        model=model,
        worker_config=SimpleNamespace(model=worker) if worker else None,
    )
    callbacks = MagicMock()
    callbacks.on_subagent_event_factory = None
    return _load_tool_class()(config=config, callbacks=callbacks, tracker=None)


def _ok(handoff_text: str = "[signpost]\n\n# idx") -> MagicMock:
    result = MagicMock()
    result.is_ok = True
    result.status = "ok"
    result.handoff_text = handoff_text
    return result


def _write(tmp_path: Path, name: str = "big.txt", lines: int = 50) -> Path:
    f = tmp_path / name
    f.write_text("\n".join(f"line{i}" for i in range(1, lines + 1)), encoding="utf-8")
    return f


class TestReadLargeFileTool:
    def test_tool_name(self, tmp_path):
        assert _make_tool(tmp_path).name == "read_large_file"

    def test_runs_reader_with_selection_and_query(self, tmp_path):
        _write(tmp_path)
        tool = _make_tool(tmp_path)
        with patch("tools.subagent_api.run_subagent", return_value=_ok()) as mock_run:
            result = tool.run(path="big.txt", query="find line 7")

        kwargs = mock_run.call_args.kwargs
        assert kwargs["preset"] == "read-large-file"
        spec = kwargs["reader_job_spec"]
        assert spec.query == "find line 7"
        assert spec.parent_reserve == 16_384
        assert spec.selection.text.startswith("line1\nline2")
        assert spec.selection.scope == "all 50 lines of big.txt"
        assert "parent_context" not in kwargs
        assert result == "[signpost]\n\n# idx"

    def test_offset_limit_select_a_range(self, tmp_path):
        _write(tmp_path)
        tool = _make_tool(tmp_path)
        with patch("tools.subagent_api.run_subagent", return_value=_ok()) as mock_run:
            tool.run(path="big.txt", offset=11, limit=5)
        sel = mock_run.call_args.kwargs["reader_job_spec"].selection
        assert sel.text == "line11\nline12\nline13\nline14\nline15"
        assert sel.spans[0].line_start == 11

    def test_result_cached(self, tmp_path):
        _write(tmp_path)
        tool = _make_tool(tmp_path)
        with patch("tools.subagent_api.run_subagent", return_value=_ok("digest")) as mock_run:
            first = tool.run(path="big.txt", query="Q")
            second = tool.run(path="big.txt", query="  q ")   # normalised query
        assert mock_run.call_count == 1
        assert first == "digest"
        assert second == "(cached) digest"

    def test_cache_keyed_on_content_query_and_model(self, tmp_path):
        f = _write(tmp_path)
        with patch("tools.subagent_api.run_subagent", return_value=_ok()) as mock_run:
            _make_tool(tmp_path).run(path="big.txt")
            _make_tool(tmp_path).run(path="big.txt", query="other")
            _make_tool(tmp_path, worker="another-model").run(path="big.txt")
            f.write_text("changed", encoding="utf-8")
            _make_tool(tmp_path).run(path="big.txt")
        assert mock_run.call_count == 4

    def test_failure_not_cached(self, tmp_path):
        _write(tmp_path)
        tool = _make_tool(tmp_path)
        failed = MagicMock(is_ok=False, status="timeout", pid=1234, message="",
                           exit_code=None, output_tail="")
        with patch("tools.subagent_api.run_subagent", return_value=failed) as mock_run:
            result = tool.run(path="big.txt")
            tool.run(path="big.txt")
        assert "timeout" in result
        assert "1234" in result
        assert mock_run.call_count == 2

    def test_empty_file_rejected_without_reader(self, tmp_path):
        (tmp_path / "empty.txt").write_text("", encoding="utf-8")
        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = _make_tool(tmp_path).run(path="empty.txt")
        assert "no content" in result
        mock_run.assert_not_called()

    def test_load_errors_returned(self, tmp_path):
        (tmp_path / "pic.png").write_bytes(b"\x89PNG")
        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = _make_tool(tmp_path).run(path="pic.png")
        assert result.startswith("Error (DAGI_CANNOT_PROCESS):")
        mock_run.assert_not_called()

    def test_reads_saved_tool_output(self, tmp_path):
        """Paths from an output-filter marker work like any other file."""
        from tools.output_filter import filter_tool_output
        big = "\n".join(f"out {i}" for i in range(20_000))
        ctx, _ = filter_tool_output(big, 1_000, tmp_path)
        saved = ctx.split("Full text: ", 1)[1].split("\n", 1)[0]
        with patch("tools.subagent_api.run_subagent", return_value=_ok()) as mock_run:
            _make_tool(tmp_path).run(path=saved)
        assert mock_run.call_args.kwargs["reader_job_spec"].selection.text == big
