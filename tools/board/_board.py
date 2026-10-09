"""Session-bound message board tools and shared compact post rendering."""
from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path

from agent._board_files import validate_attachment_id
from agent.base_tool import BaseTool
from agent.protocol import ToolResult
from tools._path_guard import validate_path

_MAX_FILE = 10 * 1024 * 1024
_MAX_ID = 2**63 - 1
_SUPPORTED_SUFFIXES = frozenset({".gif", ".png", ".jpg", ".jpeg"})


def _scan_memes(memes_root: Path) -> dict[str, Path]:
    if not memes_root.is_dir():
        return {}
    return {p.stem: p for p in sorted(memes_root.iterdir())
            if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES}


def _build_description(meme_stems: list[str]) -> str:
    base = "Post a message to the message board, optionally with a meme and attachments."
    if not meme_stems:
        return base + " No memes currently available."
    return base + f" Available memes: {', '.join(meme_stems)}."


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _format_attachment(att: dict) -> str:
    name = att["name"]
    if len(name) > 40:
        name = name[:40] + "…"
    icon = "🖼" if att["kind"] == "image" else "📎"
    return f"    {icon} {name} ({human_size(att['size'])}) [{att['id']}]"


def format_post(post: dict, me: str) -> str:
    # Maximum line: 19-digit ids, 17-char timestamp, 41-char author, own marker,
    # 700 text, 64 meme and reply suffix: <900. Four attachment lines <80 each.
    # Ten posts plus separators and hint therefore stay below 12,300 characters.
    timestamp = post["created_at"][:16].replace("T", " ") + "Z"
    own = " (you)" if post["author"] == me else ""
    line = f"#{post['id']} {timestamp} {post['author']}{own}: {post['text']}"
    if post.get("meme"):
        line += f" [meme: {post['meme']}]"
    if post.get("reply_to") is not None:
        line += f" (re #{post['reply_to']})"
    return "\n".join([line, *map(_format_attachment, post.get("attachments", []))])


class ReadBoardTool(BaseTool):
    name = "read_board"
    description = "Read new board messages, optionally only messages mentioning you."
    _parameters = {"type": "object", "properties": {
        "mentions_only": {"type": "boolean", "default": False},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10}}}

    def __init__(self, *, session):
        self._session = session

    def run(self, mentions_only: bool = False, limit: int = 10) -> str:
        if type(limit) is not int or type(mentions_only) is not bool:
            raise ValueError("limit must be an integer and mentions_only must be a boolean")
        limit = max(1, min(10, limit))
        posts = self._session.read(limit=limit, mentions_only=mentions_only)
        if not posts:
            return "(no new posts)"
        result = "\n".join(format_post(p, self._session.handle) for p in posts)
        if len(posts) == limit:
            result += "\nMore posts may be waiting — call read_board again."
        return result


def _post_files(paths, cwd: Path, roots) -> list[Path]:
    if not isinstance(paths, list) or len(paths) > 4:
        raise ValueError("attachments must be an array of at most 4 paths")
    result = []
    for name in paths:
        if not isinstance(name, str):
            raise ValueError("attachment paths must be strings")
        path = validate_path(cwd / name, roots)
        if not path.is_file():
            raise ValueError(f"attachment must be an existing file: {name}")
        if not 1 <= path.stat().st_size <= _MAX_FILE:
            raise ValueError(f"attachment must contain 1 byte through 10 MB: {name}")
        result.append(path)
    return result


class PostBoardTool(BaseTool):
    name = "post_board"
    _parameters = {"type": "object", "properties": {
        "text": {"type": "string", "maxLength": 700},
        "meme": {"type": "string"},
        "reply_to": {"type": "integer", "minimum": 1, "maximum": _MAX_ID},
        "attachments": {"type": "array", "items": {"type": "string"}, "maxItems": 4}},
        "required": ["text"]}

    def __init__(self, *, session, memes_root: Path, cwd: Path, allowed_roots):
        self._session, self._cwd, self._roots = session, cwd, allowed_roots
        self._memes = _scan_memes(memes_root)
        self.description = _build_description(sorted(self._memes))

    def run(self, text: str, *, meme=None, reply_to=None, attachments=None) -> str:
        if not isinstance(text, str) or not text:
            raise ValueError("text must contain 1 through 700 characters")
        if len(text) > 700:
            raise ValueError(
                f"text is {len(text)} chars (max 700) — put details in an attachment")
        if reply_to is not None and (type(reply_to) is not int or not 1 <= reply_to <= _MAX_ID):
            raise ValueError("reply_to must be a positive signed 64-bit integer")
        if meme is not None:
            if not isinstance(meme, str) or len(meme) > 64:
                raise ValueError("meme must be a string of at most 64 characters")
            if meme not in self._memes:
                raise ValueError(f"Meme {meme!r} not found. Available: {sorted(self._memes)}")
        files = _post_files(attachments if attachments is not None else [], self._cwd, self._roots)
        post = self._session.post(text, meme=meme, reply_to=reply_to, files=files)
        return f"Posted #{post['id']}."


def _check_cache_component(path: Path, *, directory: bool) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    reparse = getattr(info, "st_file_attributes", 0) & 0x400
    if stat.S_ISLNK(info.st_mode) or reparse:
        raise ValueError("board cache must not contain links or junctions")
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        raise ValueError("board cache contains an invalid file or directory")


def _prepare_cache(cwd: Path, roots, attachment_id: str) -> None:
    root = cwd.resolve()
    board = root / ".dagi" / "board"
    cache = board / "attachments"
    validate_path(cache / attachment_id, roots)
    for path in (root / ".dagi", board, cache, cache / attachment_id):
        _check_cache_component(path, directory=True)
    ignore = board / ".gitignore"
    validate_path(ignore, roots)
    _check_cache_component(ignore, directory=False)
    board.mkdir(parents=True, exist_ok=True)
    try:
        with ignore.open("x", encoding="utf-8") as stream:
            stream.write("*\n")
    except FileExistsError:
        _check_cache_component(ignore, directory=False)


class FetchAttachmentTool(BaseTool):
    name = "fetch_attachment"
    description = (
        "Save a board attachment locally. An image attachment is also shown to you in the "
        "next message; open any other file with read."
    )
    _parameters = {"type": "object", "properties": {
        "attachment_id": {"type": "string", "pattern": "^att_[0-9a-f]{12}$"}},
        "required": ["attachment_id"]}

    def __init__(self, *, session, cwd: Path, allowed_roots, image_reader=None):
        self._session, self._cwd, self._roots = session, cwd, allowed_roots
        self._image_reader = image_reader

    def run(self, attachment_id: str):
        validate_attachment_id(attachment_id)
        _prepare_cache(self._cwd, self._roots, attachment_id)
        att, path = self._session.fetch(attachment_id, self._cwd)
        saved = f"Saved {att['name']} ({human_size(att['size'])}, {att['kind']}) to {path}"
        if att.get("kind") != "image" or self._image_reader is None:
            return f"{saved} — open it with read."
        result = self._image_reader(Path(path))
        if isinstance(result, ToolResult):
            return replace(result, output=f"{saved}. {result.output}")
        return f"{saved}, but it could not be shown: {result}"
