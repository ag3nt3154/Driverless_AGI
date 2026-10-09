"""Thread-safe SQLite storage for the message board HTTP service."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .blobs import sanitize_name, sniff_kind, sniff_mime, write_blob

HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}_[0-9a-f]{8}")
_MENTION_RE = re.compile(r"@([a-z0-9][a-z0-9-]{0,31}_[0-9a-f]{8})(?![\w-])")
MAX_TEXT, MAX_MEME, MAX_LIMIT, MAX_ATTACHMENTS = 700, 64, 200, 4
MAX_ATTACHMENT = 10 * 1024 * 1024
MAX_ID = 2**63 - 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    handle TEXT PRIMARY KEY, display_name TEXT NOT NULL, kind TEXT NOT NULL,
    host TEXT NOT NULL, registered_at TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, board TEXT NOT NULL, author TEXT NOT NULL,
    text TEXT NOT NULL, mentions TEXT NOT NULL, meme TEXT, reply_to INTEGER,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS post_mentions (post_id INTEGER NOT NULL, handle TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL, mime TEXT NOT NULL,
    kind TEXT NOT NULL, sha256 TEXT NOT NULL, uploader TEXT NOT NULL,
    created_at TEXT NOT NULL, post_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_attachments_post ON attachments(post_id);
CREATE INDEX IF NOT EXISTS idx_post_mentions ON post_mentions(handle, post_id);
"""


class StoreError(Exception):
    """A refused request with an HTTP-compatible error code and status."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def extract_mentions(text: str) -> list[str]:
    """Return well-formed mentioned handles in first-seen order."""
    return list(dict.fromkeys(_MENTION_RE.findall(text)))


def _invalid(message: str) -> None:
    raise StoreError("INVALID", message, 422)


def _validate_id(value: int, *, minimum: int = 1) -> None:
    if type(value) is not int or not minimum <= value <= MAX_ID:
        _invalid(f"id must be an integer from {minimum} through {MAX_ID}")


def _attachment_record(row: sqlite3.Row) -> dict:
    record = dict(row)
    record.pop("post_id")
    return record


class BoardStore:
    """One WAL database; a lock guards each connection and full write transaction."""

    def __init__(self, db_path: Path) -> None:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._blob_dir = db_path.parent / "blobs"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _member(self, handle: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM members WHERE handle=?", (handle,)).fetchone()
        if row is None:
            raise StoreError("UNKNOWN_AUTHOR", f"member {handle!r} is not registered", 404)
        return row

    def register_member(self, handle: str, kind: str, display_name: str | None = None,
                        host: str = "") -> tuple[dict, bool]:
        if not isinstance(handle, str) or not HANDLE_RE.fullmatch(handle):
            _invalid("handle must have the form <slug>_<8 lowercase hex digits>")
        if kind not in ("agent", "user"):
            _invalid("kind must be agent or user")
        with self._transaction():
            row = self._conn.execute("SELECT * FROM members WHERE handle=?", (handle,)).fetchone()
            created = row is None
            stamp = _now()
            if row is not None:
                if row["kind"] != kind or row["host"] != host:
                    raise StoreError("HANDLE_TAKEN", f"handle {handle!r} is already in use", 409)
                self._conn.execute("UPDATE members SET last_seen=? WHERE handle=?", (stamp, handle))
            else:
                self._conn.execute("INSERT INTO members VALUES (?,?,?,?,?,?)",
                                   (handle, display_name or handle, kind, host, stamp, stamp))
            return dict(self._member(handle)), created

    def list_members(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM members ORDER BY registered_at, handle")
            return [dict(row) for row in rows]

    def add_attachment(self, uploader: str, name: str, data: bytes) -> dict:
        with self._transaction():
            self._member(uploader)
            if not data:
                _invalid("attachment must not be empty")
            if len(data) > MAX_ATTACHMENT:
                raise StoreError("TOO_LARGE", "attachment exceeds 10 MB", 413)
            name = sanitize_name(name)
            digest = write_blob(self._blob_dir, data)
            attachment_id = "att_" + uuid.uuid4().hex[:12]
            self._conn.execute("INSERT INTO attachments VALUES (?,?,?,?,?,?,?,?,NULL)",
                               (attachment_id, name, len(data), sniff_mime(data[:12], name),
                                sniff_kind(data[:12]), digest, uploader, _now()))
            return _attachment_record(self._attachment(attachment_id))

    def _attachment(self, attachment_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM attachments WHERE id=?", (attachment_id,),
        ).fetchone()
        if row is None:
            raise StoreError("UNKNOWN_ATTACHMENT", f"attachment {attachment_id!r} not found", 404)
        return row

    def get_attachment(self, attachment_id: str) -> tuple[dict, Path]:
        with self._lock:
            record = _attachment_record(self._attachment(attachment_id))
            return record, self._blob_dir / record["sha256"]

    def _validate_content(self, text: str, meme: str | None) -> None:
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
            _invalid("text must contain 1 through 700 characters")
        if meme is not None and (not isinstance(meme, str) or len(meme) > MAX_MEME):
            _invalid("meme must contain at most 64 characters")

    def _validate_attachments(self, attachments: list[str]) -> None:
        if len(attachments) > MAX_ATTACHMENTS:
            _invalid("a post can have at most 4 attachments")
        if any(not isinstance(item, str) for item in attachments):
            _invalid("attachment ids must be strings")
        if len(set(attachments)) != len(attachments):
            _invalid("attachment ids must be unique")

    def _check_post_references(self, author: str, reply_to: int | None,
                               attachments: list[str]) -> None:
        self._member(author)
        if reply_to is not None:
            _validate_id(reply_to)
            row = self._conn.execute("SELECT id FROM posts WHERE id=?", (reply_to,)).fetchone()
            if row is None:
                raise StoreError("UNKNOWN_POST", f"reply post {reply_to} not found", 404)
        for attachment_id in attachments:
            row = self._attachment(attachment_id)
            if row["uploader"] != author:
                _invalid("attachments must be uploaded by the post author")
            if row["post_id"] is not None:
                raise StoreError("ATTACHMENT_USED", f"attachment {attachment_id} is used", 409)

    def create_post(self, author: str, text: str, *, meme: str | None = None,
                    reply_to: int | None = None, attachments=()) -> dict:
        attachments = list(attachments)
        self._validate_content(text, meme)
        self._validate_attachments(attachments)
        with self._transaction():
            self._check_post_references(author, reply_to, attachments)
            mentions, stamp = extract_mentions(text), _now()
            cursor = self._conn.execute("INSERT INTO posts "
                                        "(board,author,text,mentions,meme,reply_to,created_at) "
                                        "VALUES ('default',?,?,?,?,?,?)",
                                        (author, text, json.dumps(mentions), meme, reply_to, stamp))
            post_id = cursor.lastrowid
            self._conn.executemany("INSERT INTO post_mentions VALUES (?,?)",
                                   [(post_id, mention) for mention in mentions])
            self._conn.executemany("UPDATE attachments SET post_id=? WHERE id=?",
                                   [(post_id, item) for item in attachments])
            self._conn.execute("UPDATE members SET last_seen=? WHERE handle=?", (stamp, author))
            return self._post_row(self._conn.execute(
                "SELECT * FROM posts WHERE id=?", (post_id,)).fetchone())

    def _post_row(self, row: sqlite3.Row) -> dict:
        post = dict(row)
        post["mentions"] = json.loads(post["mentions"])
        rows = self._conn.execute("SELECT * FROM attachments WHERE post_id=? ORDER BY rowid",
                                  (post["id"],))
        post["attachments"] = [_attachment_record(item) for item in rows]
        return post

    def list_posts(self, after: int | None = None, limit: int = 50,
                   mention: str | None = None) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            _invalid("limit must be an integer from 1 through 200")
        clauses, params = ["1=1"], []
        if after is not None:
            _validate_id(after, minimum=0)
            clauses.append("id > ?")
            params.append(after)
        if mention is not None:
            clauses.append("id IN (SELECT post_id FROM post_mentions WHERE handle=?)")
            params.append(mention)
        where = " WHERE " + " AND ".join(clauses)
        order = "ASC" if after is not None else "DESC"
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM posts{where} ORDER BY id {order} LIMIT ?",
                                      [*params, limit]).fetchall()
            posts = [self._post_row(row) for row in rows]
            return posts if after is not None else posts[::-1]

    def latest_id(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COALESCE(MAX(id), 0) FROM posts").fetchone()[0]

