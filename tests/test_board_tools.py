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
from tools.board import BoardMembersTool, FetchAttachmentTool, PostBoardTool, ReadBoardTool
from tools.board._board import format_post, human_size

A = "main_3f9a1c2e"
W = "worker_1a2b3c4d"


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
        client.register(A, "agent", key="k" * 43)
        session = BoardSession(client, A, "k" * 43)
        requests.clear()
        yield SimpleNamespace(post=PostBoardTool(session=session, memes_root=memes,
                                                cwd=project, allowed_roots=[project]),
                              read=ReadBoardTool(session=session),
                              fetch=FetchAttachmentTool(session=session, cwd=project,
                                                        allowed_roots=[project]),
                              members=BoardMembersTool(session=session),
                              session=session, project=project, memes=memes, requests=requests,
                              store=store)
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
    members = [{"handle": "y" * 32 + f"_{n:08x}", "online": True, "banned": False}
               for n in range(30)]
    client = SimpleNamespace(members=lambda: members)
    output = ReadBoardTool(session=SimpleNamespace(handle=author, read=read, client=client)).run(
        limit=50)
    assert limits == [10] and len(output) < 13000
    assert "+20 more" in output
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


def test_post_warns_about_mentions_that_match_no_member(tools):
    tools.session.client.register(W, "agent", key="w" * 43)
    result = tools.post.run(text="@worker hi, also @worker-1a2b3c4d and @worker_1a2b3c4d")
    assert result == (
        "Posted #1.\n"
        "⚠ @worker, @worker-1a2b3c4d matched no board member — they were not notified. "
        f"Online members: {A} (you), board-admin, {W}. Mention with the full handle, e.g. @{W}.")


def test_post_with_exact_mentions_or_emails_has_no_warning(tools):
    tools.session.client.register(W, "agent", key="w" * 43)
    assert tools.post.run(text=f"@{W}: ping, @board-admin") == "Posted #1."
    tools.requests.clear()
    assert tools.post.run(text="mail ops@example.com") == "Posted #2."
    assert "/members" not in tools.requests  # posts without mentions skip the lookup


def test_read_board_names_you_and_the_online_members(tools):
    tools.session.client.register(W, "agent", key="w" * 43)
    tools.post.run(text="hello")
    output = tools.read.run()
    assert output.splitlines()[0] == f"You are {A}. Online members: {A} (you), board-admin, {W}."


def test_post_board_description_explains_full_handle_mentions(tools):
    assert "@worker_1a2b3c4d" in tools.post.description


def test_post_notes_a_recorded_mention_of_an_offline_handle(tools):
    """A well-formed handle is recorded (and the GUI still wakes it) even when not online."""
    result = tools.post.run(text=f"@{W} are you there?")
    assert result == (
        "Posted #1.\n"
        f"Note: @{W} is not online right now; the mention is recorded. "
        f"Online members: {A} (you), board-admin.")
    assert tools.session.client.posts()[0]["mentions"] == [W]


def test_member_lookup_failure_never_fails_post_or_read(tools):
    def fail():
        raise BoardError("UNREACHABLE", "down")
    tools.session.client.members = fail
    assert tools.post.run(text="@worker hi") == "Posted #1."
    assert tools.read.run().splitlines()[0] == f"You are {A}."


def test_warning_falls_back_to_an_example_handle_when_alone(tools):
    result = tools.post.run(text="@worker hi")
    assert result.endswith("e.g. @worker_1a2b3c4d.")


def test_board_members_lists_online_handles_only(tools):
    from datetime import datetime, timedelta, timezone

    tools.session.client.register(W, "agent", key="w" * 43)
    X = "worker_0ffab1de"
    tools.session.client.register(X, "agent", key="x" * 43)
    stale = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    tools.store._conn.execute("UPDATE members SET last_seen=? WHERE handle=?", (stale, X))

    assert tools.members.run() == (
        f"You are {A}. Online members: {A} (you), board-admin, {W}.")


def test_board_members_reports_unreachable_board(tools):
    def fail():
        raise BoardError("UNREACHABLE", "down")
    tools.session.client.members = fail
    assert tools.members.run() == "Error: the message board is not reachable right now."


def test_registry_registers_board_members_only_with_a_board(tmp_path):
    from agent._loop_config import AgentCallbacks
    from agent.tools import create_tool_registry

    reg = create_tool_registry(cwd=tmp_path, callbacks=AgentCallbacks(board=object()))
    assert reg.get("board_members") is not None

    reg_without = create_tool_registry(cwd=tmp_path, callbacks=AgentCallbacks())
    assert reg_without.get("board_members") is None
