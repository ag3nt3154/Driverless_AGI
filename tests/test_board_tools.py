"""Board tools, bounded rendering and preflight file validation."""
import stat
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.board_client import BoardClient, BoardError, BoardSession
from agent.registry import ToolRegistry
from services.message_board.app import create_app
from services.message_board.store import BoardStore, MAX_ATTACHMENT
from tools.board import FetchAttachmentTool, PostBoardTool, ReadBoardTool
from tools.board._board import format_post, human_size

A = "main_3f9a1c2e"


@pytest.fixture
def tools(tmp_path):
    project, memes = tmp_path / "project", tmp_path / "memes"
    project.mkdir()
    memes.mkdir()
    (memes / "cinema.gif").write_bytes(b"GIF89a")
    (memes / "eat.png").write_bytes(b"PNG")
    (memes / "ignored.txt").write_text("ignored")
    store = BoardStore(tmp_path / "server" / "b.sqlite3")
    app = create_app(store)
    requests = []
    with TestClient(app) as http:
        http.event_hooks["request"].append(lambda request: requests.append(request.url.path))
        client = BoardClient("http://board", http=http, download_http=lambda: httpx.AsyncClient(
            base_url="http://board", transport=httpx.ASGITransport(app=app)))
        client.register(A, "agent")
        session = BoardSession(client, A)
        requests.clear()
        yield SimpleNamespace(post=PostBoardTool(session=session, memes_root=memes,
                                                cwd=project, allowed_roots=[project]),
                              read=ReadBoardTool(session=session),
                              fetch=FetchAttachmentTool(session=session, cwd=project,
                                                        allowed_roots=[project]),
                              session=session, project=project, memes=memes, requests=requests)
    store.close()


def test_output_format_meme_reply_marker_and_read_hint(tools):
    assert tools.post.run(text="one", meme="cinema") == "Posted #1."
    assert tools.post.run(text="two", reply_to=1) == "Posted #2."
    output = tools.read.run(limit=2)
    assert f"{A} (you): one [meme: cinema]" in output
    assert f"{A} (you): two (re #1)" in output
    assert output.endswith("More posts may be waiting — call read_board again.")
    assert tools.read.run() == "(no new posts)"


def test_attachment_render_and_fetch_roundtrip(tools):
    source = tools.project / "hello.txt"
    source.write_bytes(b"secret file contents")
    tools.post.run(text="details", attachments=["hello.txt"])
    output = tools.read.run()
    assert "📎 hello.txt (20 B) [att_" in output and "secret file contents" not in output
    post = tools.session.client.posts()[0]
    attachment = post["attachments"][0]
    result = tools.fetch.run(attachment_id=attachment["id"])
    saved = tools.project / ".dagi/board/attachments" / attachment["id"] / "hello.txt"
    assert saved.read_bytes() == source.read_bytes()
    assert result == f"Saved hello.txt (20 B, file) to {saved} — open it with read."
    assert (tools.project / ".dagi/board/.gitignore").read_text() == "*\n"


def test_worst_case_output_is_bounded_and_fields_remain():
    author = "x" * 32 + "_1234abcd"
    attachment = {"id": "att_" + "f" * 12, "name": "n" * 128,
                  "size": MAX_ATTACHMENT, "kind": "image"}
    post = {"id": 2**63 - 1, "author": author, "text": "t" * 700,
            "created_at": "2026-10-08T23:59:59Z", "meme": "m" * 64,
            "reply_to": 2**63 - 1, "attachments": [attachment] * 4}
    limits = []
    def read(**kwargs):
        limits.append(kwargs["limit"])
        return [post] * 10
    output = ReadBoardTool(session=SimpleNamespace(handle=author, read=read)).run(limit=50)
    assert limits == [10] and len(output) < 13000
    assert output.count("t" * 700) == 10 and output.count("m" * 64) == 10
    assert output.count("n" * 40 + "…") == 40 and "n" * 41 not in output
    assert "(you)" in output and f"(re #{2**63 - 1})" in output
    assert "2026-10-08 23:59Z" in output and "🖼" in output


@pytest.mark.parametrize("size,expected", [(0, "0 B"), (1023, "1023 B"), (12288, "12 KB"),
                                          (10 * 1024 * 1024, "10.0 MB")])
def test_human_size(size, expected):
    assert human_size(size) == expected


@pytest.mark.parametrize("case", ["long", "empty", "missing", "outside", "large", "fifth"])
def test_invalid_post_preflight_never_uploads(tools, tmp_path, case):
    source = tools.project / "fine.txt"
    source.write_text("fine")
    kwargs = {"text": "ok", "attachments": ["fine.txt"]}
    if case == "long":
        kwargs["text"] = "x" * 701
    elif case == "empty":
        kwargs["text"] = ""
    elif case == "missing":
        kwargs["attachments"].append("missing.txt")
    elif case == "outside":
        outside = tmp_path / "outside.txt"
        outside.write_text("outside")
        kwargs["attachments"].append(str(outside))
    elif case == "large":
        large = tools.project / "large.bin"
        with large.open("wb") as stream:
            stream.truncate(MAX_ATTACHMENT + 1)
        kwargs["attachments"].append("large.bin")
    else:
        kwargs["attachments"] *= 5
    with pytest.raises(ValueError) as caught:
        tools.post.run(**kwargs)
    if case == "long":
        assert "text is 701 chars (max 700) — put details in an attachment" in str(caught.value)
    assert tools.requests == []


def test_meme_schema_description_and_invalid_preflight(tools, tmp_path):
    parameters = tools.post.schema()["function"]["parameters"]
    assert parameters["required"] == ["text"]
    assert set(parameters["properties"]) == {"text", "meme", "reply_to", "attachments"}
    assert parameters["properties"]["reply_to"] == {
        "type": "integer", "minimum": 1, "maximum": 2**63 - 1,
    }
    assert "cinema" in tools.post.description and "eat" in tools.post.description
    assert "ignored" not in tools.post.description
    with pytest.raises(ValueError, match="Available.*cinema.*eat"):
        tools.post.run(text="hello", meme="missing")
    assert tools.requests == []
    empty = PostBoardTool(session=tools.session, cwd=tools.project, allowed_roots=[tools.project],
                          memes_root=tmp_path / "missing")
    assert "No memes" in empty.description


@pytest.mark.parametrize("reply_to", [True, False, 0, -1, 2**63, "1", 1.0])
def test_invalid_reply_is_rejected_before_upload(tools, reply_to):
    source = tools.project / "fine.txt"
    source.write_text("fine")

    with pytest.raises(ValueError, match="positive signed 64-bit integer"):
        tools.post.run(text="reply", reply_to=reply_to, attachments=["fine.txt"])

    assert tools.requests == []


@pytest.mark.parametrize("meme", [True, 7, "m" * 65])
def test_invalid_meme_is_rejected_before_upload(tools, meme):
    source = tools.project / "fine.txt"
    source.write_text("fine")

    with pytest.raises(ValueError, match="string of at most 64 characters"):
        tools.post.run(text="meme", meme=meme, attachments=["fine.txt"])

    assert tools.requests == []


@pytest.mark.parametrize("component", ["board", ".gitignore"])
def test_invalid_cache_component_is_rejected_before_fetch(tools, component):
    board = tools.project / ".dagi" / "board"
    if component == "board":
        board.parent.mkdir()
        board.write_text("not a directory")
    else:
        board.mkdir(parents=True)
        (board / ".gitignore").mkdir()

    with pytest.raises(ValueError, match="invalid file or directory"):
        tools.fetch.run(attachment_id="att_123456789abc")

    assert tools.requests == []


def test_cache_gitignore_link_is_rejected_before_fetch(tools, monkeypatch):
    board = tools.project / ".dagi" / "board"
    board.mkdir(parents=True)
    ignore = board / ".gitignore"
    real_lstat = Path.lstat

    def linked_gitignore(path):
        if path == ignore:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", linked_gitignore)
    with pytest.raises(ValueError, match="links or junctions"):
        tools.fetch.run(attachment_id="att_123456789abc")

    assert tools.requests == []


def test_malformed_fetch_and_registry_error(tools):
    with pytest.raises(ValueError):
        tools.fetch.run(attachment_id="../invalid")
    assert tools.requests == []
    registry = ToolRegistry()
    registry.register(ReadBoardTool(session=SimpleNamespace(
        read=lambda **kwargs: (_ for _ in ()).throw(BoardError("UNREACHABLE", "board offline")))))
    assert registry.dispatch("read_board", {}) == "Error: board offline"


def _png(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (4, 3), (255, 0, 0)).save(path, format="PNG")


def test_fetched_image_is_attached_for_the_model(tools):
    from agent.protocol import SideEffect
    from tools.read import ReadTool

    _png(tools.project / "red.png")
    tools.post.run(text="look", attachments=["red.png"])
    attachment = tools.session.client.posts()[0]["attachments"][0]
    assert attachment["kind"] == "image"
    reader = ReadTool(cwd=tools.project, allowed_roots=[tools.project])
    fetch = FetchAttachmentTool(session=tools.session, cwd=tools.project,
                                allowed_roots=[tools.project], image_reader=reader.read_image)
    result = fetch.run(attachment_id=attachment["id"])
    saved = tools.project / ".dagi/board/attachments" / attachment["id"] / "red.png"
    assert result.side_effect is SideEffect.ATTACH_IMAGE
    assert result.side_effect_data["path"] == str(saved)
    image = result.side_effect_data["image"]
    assert (image.width, image.height) == (4, 3)
    assert result.output.startswith("Saved red.png (") and str(saved) in result.output
    assert "attached in the next message" in result.output


def test_unreadable_image_falls_back_to_text(tools):
    _png(tools.project / "red.png")
    tools.post.run(text="look", attachments=["red.png"])
    attachment = tools.session.client.posts()[0]["attachments"][0]
    fetch = FetchAttachmentTool(session=tools.session, cwd=tools.project,
                                allowed_roots=[tools.project],
                                image_reader=lambda path: "Error: too large")
    result = fetch.run(attachment_id=attachment["id"])
    assert isinstance(result, str) and result.endswith("could not be shown: Error: too large")


def test_registry_wires_fetch_attachment_to_the_read_image_path(tmp_path):
    from agent._loop_config import AgentCallbacks
    from agent.tools import create_tool_registry

    reg = create_tool_registry(cwd=tmp_path, callbacks=AgentCallbacks(board=object()))
    fetch = reg.get("fetch_attachment")
    assert fetch is not None and fetch._image_reader is not None
    assert fetch._image_reader.__func__.__name__ == "read_image"
