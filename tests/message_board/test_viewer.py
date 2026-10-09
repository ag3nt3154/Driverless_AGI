"""Read-only web viewer: route, XSS guards, browser behaviour and packaged installs."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from services.message_board.app import create_app
from services.message_board.store import BoardStore

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "services" / "message_board" / "static" / "index.html"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NETWORK_HINTS = ("NewConnectionError", "Failed to establish", "getaddrinfo", "ConnectTimeout",
                 "ReadTimeout", "No matching distribution", "Could not find a version",
                 "ProxyError", "Max retries exceeded", "Temporary failure in name resolution")
HARNESS = Path(__file__).with_name("viewer_harness.js")
RUN_SLOW = pytest.mark.skipif(os.environ.get("DAGI_RUN_SLOW") != "1",
                              reason="clean-venv install checks need network; set DAGI_RUN_SLOW=1")


@pytest.fixture
def board(tmp_path):
    store = BoardStore(tmp_path / "board.sqlite3")
    yield store
    store.close()


def test_viewer_route_serves_packaged_page_from_any_cwd(board, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(board)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == PAGE.read_bytes()


def test_viewer_is_public_while_api_needs_token(board):
    with TestClient(create_app(board, "secret")) as client:
        page = client.get("/")
        assert page.status_code == 200 and page.content == PAGE.read_bytes()
        assert page.headers["x-content-type-options"] == "nosniff"
        assert client.get("/posts").status_code == 401


SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
         "new Function", "setAttribute(", "location.href")


def _sink_violations(source: str) -> list[str]:
    found = [sink for sink in SINKS if sink in source]
    if re.search(r"\blocation\s*=(?!=)", source):
        found.append("location =")
    # Only blob URLs created by the page itself may reach src/srcset/href.
    assignments = re.findall(r"\.(?:src|srcset|href)\s*=\s*([^;]+);", source)
    if not assignments or set(assignments) != {"url"}:
        found.append(f"src/srcset/href assignments {sorted(set(assignments))}")
    return found


def test_page_has_no_html_injection_sinks():
    assert _sink_violations(PAGE.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("mutation", [
    "node.innerHTML = p.text;", "node.setAttribute(\"href\", p.text);",
    "location = p.text;", "window.location.href = p.text;", "img.srcset = p.text;",
    "img.src = p.text;", "document.write(p.text);",
])
def test_sink_guard_catches_mutations(mutation):
    source = PAGE.read_text(encoding="utf-8").replace("<script>", "<script>\n" + mutation, 1)
    assert _sink_violations(source)


def _strip_comments(source: str) -> str:
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(^|\s)//[^\n]*", r"\1", source)


def test_page_is_self_contained_and_small():
    source = PAGE.read_text(encoding="utf-8")
    assert "http://" not in _strip_comments(source)
    assert "https://" not in _strip_comments(source)
    assert not re.search(r"<(?:script|link|img|iframe)[^>]*\s(?:src|href)=", source)
    assert len(source.splitlines()) <= 400


# --- behaviour in a JS runtime (node) with a fake DOM and fetch -----------------------------

def _harness(scenario: str, cwd: Path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the browser check covers the page script")
    result = subprocess.run([node, str(HARNESS), str(PAGE), scenario], capture_output=True,
                            text=True, timeout=30, cwd=cwd, creationflags=NO_WINDOW)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_page_script_streams_dedupes_orders_trims_and_prompts_for_token(tmp_path):
    report = _harness("main", tmp_path)
    first = report["first"]
    assert first["status"] == "token required" and first["authVisible"] is True
    assert first["requests"] == [["/posts?limit=50", None]]
    final = report["final"]
    assert final["token"] == "secret" and final["authVisible"] is False
    paths = [path for path, _ in final["requests"]]
    assert paths[:2] == ["/posts?limit=50", "/posts?limit=50"]
    assert "/attachments/att_0123456789ab" in paths
    assert "/attachments/att_bad" not in " ".join(paths)
    streams = [path for path in paths if path.startswith("/stream")]
    assert streams[:2] == ["/stream?after=2", "/stream?after=214"]
    assert all(auth == "Bearer secret" for _, auth in final["requests"][1:])
    assert len(final["ids"]) == 200 and final["ids"][:3] == [214, 213, 212]
    assert len(set(final["ids"])) == len(final["ids"])  # 213 was re-sent after 214
    assert final["ids"] == sorted(final["ids"], reverse=True)
    assert final["ids"][-1] == 15
    assert final["hostileText"] == "<img src=x onerror=alert(1)>"
    assert final["imageSrc"].startswith("blob:") and final["revoked"] == [final["imageSrc"]]
    assert final["status"] == "connected"


def test_stream_that_closes_without_events_backs_off(tmp_path):
    final = _harness("eof", tmp_path)["final"]
    # Headers alone do not reset the backoff; only an event or ping does.
    assert final["countdowns"][:4] == [1, 2, 4, 8]


def test_hanging_requests_time_out_and_reconnect(tmp_path):
    final = _harness("hang", tmp_path)["final"]
    paths = [path for path, _ in final["requests"] if not path.startswith("/attachments")]
    assert paths == ["/posts?limit=50", "/posts?limit=50", "/stream?after=2",
                     "/stream?after=2"]
    assert final["countdowns"] == [1, 2] and final["status"] == "connected"
    assert final["ids"] == [2, 1]


# --- packaging and clean installs -----------------------------------------------------------

def _copy_source(destination: Path) -> Path:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    tool = config["tool"]["setuptools"]
    tops = {pattern.split(".")[0].rstrip("*") for pattern in tool["packages"]["find"]["include"]}
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "*.egg-info", "build")
    for top in sorted(tops):
        shutil.copytree(REPO / top, destination / top, ignore=ignore)
    for module in tool["py-modules"]:
        shutil.copy2(REPO / f"{module}.py", destination)
    shutil.copy2(REPO / "pyproject.toml", destination)
    return destination


def _clean_env() -> dict:
    env = {key: value for key, value in os.environ.items()
           if key not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "DAGI_BOARD_TOKEN",
                          "PIP_USER", "PIP_TARGET", "PIP_PREFIX")}
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _run(args, cwd, timeout=600, env=None):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env or _clean_env(), creationflags=NO_WINDOW)


def _pip(python: Path, cwd: Path, *args):
    # Keep pip's build temp dirs short too (venv root is <short>/venv/Scripts/python).
    scratch = python.parents[2] / "piptmp"
    scratch.mkdir(exist_ok=True)
    env = {**_clean_env(), "TEMP": str(scratch), "TMP": str(scratch)}
    result = _run([python, "-I", "-m", "pip", "--disable-pip-version-check", "--retries", "1",
                   "--timeout", "20", *args], cwd, env=env)
    output = result.stdout + result.stderr
    if result.returncode and any(hint in output for hint in NETWORK_HINTS):
        pytest.skip("package index unreachable, clean install not possible: "
                    + output.strip().splitlines()[-1][:200])
    assert result.returncode == 0, output[-3000:]
    return result


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    source = _copy_source(tmp_path_factory.mktemp("source"))
    out = tmp_path_factory.mktemp("wheel")
    # Call the PEP 517 backend directly: pip's ephemeral wheel cache nests deep enough to
    # exceed Windows MAX_PATH under pytest's temp directories. Nothing gets installed.
    build = "import sys, setuptools.build_meta as b; b.build_wheel(sys.argv[1])"
    result = _run([sys.executable, "-c", build, out], source)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    return next(out.glob("driverless_agi-*.whl")), source


@pytest.fixture
def short_tmp(tmp_path):
    """A venv root short enough for deep site-packages paths under Windows MAX_PATH."""
    bases = [tmp_path, Path(os.environ.get("LOCALAPPDATA", tmp_path)) / "Temp"]
    base = next((item for item in bases if item.is_dir() and len(str(item)) <= 60), None)
    if base is None:
        pytest.skip("no temporary directory short enough for a clean venv on this platform")
    root = Path(tempfile.mkdtemp(prefix="dagi-viewer-", dir=base))
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _new_venv(root: Path) -> Path:
    result = _run([sys.executable, "-m", "venv", root / "venv"], root, timeout=180)
    assert result.returncode == 0, result.stderr
    return root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def test_wheel_contains_viewer_and_extras_metadata(wheel):
    path, _ = wheel
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert archive.read("services/message_board/static/index.html") == PAGE.read_bytes()
        metadata = archive.read(next(n for n in names if n.endswith(".dist-info/METADATA")))
    lines = metadata.decode().splitlines()
    requires = [line.split(":", 1)[1].strip() for line in lines if line.startswith("Requires-Dist")]
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    for pin in config["project"]["optional-dependencies"]["board"]:
        assert f'{pin}; extra == "board"' in requires, pin
    gui_self = [item for item in requires
                if item.startswith("driverless-agi[") and item.endswith('extra == "gui"')]
    assert gui_self and "board" in gui_self[0].split("]")[0]
    assert "Provides-Extra: board" in lines and "Provides-Extra: gui" in lines


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(process, url: str) -> None:
    deadline = time.monotonic() + 20
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            assert process.poll() is None, "installed board exited before readiness"
            try:
                if client.get(url + "/health").status_code == 200:
                    return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            time.sleep(.1)
    raise AssertionError("installed board did not become ready")


@pytest.mark.slow
@RUN_SLOW
def test_clean_board_install_serves_packaged_viewer(wheel, short_tmp):
    path, _ = wheel
    tmp_path = short_tmp
    python = _new_venv(tmp_path)
    work = tmp_path / "elsewhere"
    work.mkdir()
    _pip(python, work, "install", f"{path}[board]")
    located = _run([python, "-I", "-c", "import services.message_board as m; print(m.__file__)"],
                   work)
    assert Path(located.stdout.strip()).is_relative_to(tmp_path / "venv"), located.stdout
    help_run = _run([python, "-I", "-m", "services.message_board", "--help"], work, timeout=60)
    assert help_run.returncode == 0 and "serve" in help_run.stdout, help_run.stderr
    port = _unused_port()
    url = f"http://127.0.0.1:{port}"
    runtime = tmp_path / "run"
    with (tmp_path / "service.log").open("wb") as log:
        process = subprocess.Popen(
            [str(python), "-I", "-m", "services.message_board", "serve", "--port", str(port),
             "--db", str(tmp_path / "db" / "board.sqlite3"), "--runtime-dir", str(runtime)],
            cwd=work, stdout=log, stderr=log, env=_clean_env(), creationflags=NO_WINDOW)
        try:
            _wait_ready(process, url)
            page = httpx.get(url + "/", trust_env=False, timeout=5)
            assert page.status_code == 200 and page.content == PAGE.read_bytes()
            stop = _run([python, "-I", "-m", "services.message_board", "stop", "--url", url,
                         "--runtime-dir", runtime], work, timeout=30)
            assert stop.returncode == 0, stop.stdout + stop.stderr
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


@pytest.mark.slow
@RUN_SLOW
def test_editable_gui_install_path(wheel, short_tmp):
    _, source = wheel
    tmp_path = short_tmp
    python = _new_venv(tmp_path)
    report = tmp_path / "gui-report.json"
    _pip(python, tmp_path, "install", "--dry-run", "--ignore-installed", "--report", report,
         "-e", f"{source}[gui]")
    planned = {item["metadata"]["name"].lower() for item in
               json.loads(report.read_text(encoding="utf-8"))["install"]}
    assert {"driverless-agi", "pyside6", "fastapi", "uvicorn", "python-multipart",
            "textual"} <= planned
    _pip(python, tmp_path, "install", "--no-deps", "-e", source)
    probe = ("from importlib import resources; "
             "print(resources.files('services.message_board') / 'static' / 'index.html')")
    located = _run([python, "-I", "-c", probe], tmp_path)
    page = Path(located.stdout.strip())
    assert page.is_relative_to(source) and page.read_bytes() == PAGE.read_bytes(), located.stderr
