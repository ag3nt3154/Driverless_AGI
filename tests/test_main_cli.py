"""main.py prints non-cp1252 results without crashing on a Windows-default stdout."""
import io
import sys
from types import SimpleNamespace

import main


def test_main_prints_non_ascii_result_under_cp1252_stdout(monkeypatch, tmp_path):
    result = "done → ok ✓"

    class FakeLoop:
        def __init__(self, config, callbacks=None):
            pass

        def run(self, task):
            return result

        def finish(self):
            pass

    monkeypatch.setattr(main, "resolve_model_config",
                        lambda model_id=None: SimpleNamespace(project_path=None))
    monkeypatch.setattr(main, "build_cli_callbacks", lambda verbose: None)
    monkeypatch.setattr(main, "AgentLoop", FakeLoop)
    monkeypatch.setattr(sys, "argv", ["main.py", "--project", str(tmp_path), "some task"])

    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", stdout)

    main.main()
    stdout.flush()

    assert raw.getvalue().decode("utf-8") == result + "\n"
