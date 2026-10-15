"""
agent/config_editor.py — comment-preserving editor for {DAGI_ROOT}/.dagi/config.yaml.

`ConfigDocument` wraps a ruamel.yaml round-trip tree so that comments, blank
lines, key order and commented-out alternatives survive load -> edit -> save.
An unedited document serializes back to the exact text it was loaded from.

Saves are atomic (write `<name>.yaml.tmp`, then `os.replace`, retried briefly
on PermissionError) and
conflict-checked: the on-disk sha256 must still match the hash recorded at
load time unless the caller forces the write. The file's line endings (LF or
CRLF) are preserved on save; `text()` always uses LF.

`ConfigDocument.save()` does not validate: the strict pre-save checks and the
tool catalog live in `agent.config_validate`.

This module is UI-agnostic (no GUI toolkit imports). Never read the config for
editing via `config_loader.load_raw_config()` — it merges the model catalog.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import time
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark, MarkedYAMLError, YAMLError
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString
from ruamel.yaml.tokens import CommentToken


_UNSET: Any = object()

# Indices into ruamel's per-key / per-item comment slots.
_MAP_TRAILING = 2  # comment after a mapping value (end of line + following lines)
_SEQ_TRAILING = 0  # comment after a sequence item


class ConfigParseError(ValueError):
    """Text is not valid YAML or its root is not a mapping. `line` is 1-based."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.message = message
        self.line = line
        super().__init__(f"line {line}: {message}" if line is not None else message)


class ConfigConflictError(RuntimeError):
    """The file on disk changed since it was loaded."""


_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY_S = 0.05


def _replace_with_retry(src: Path, dst: Path) -> None:
    """`os.replace`, retried on PermissionError.

    On Windows the replace fails with "Access is denied" while another process
    (a file watcher, antivirus, an editor) briefly holds the target open.
    """
    for attempt in range(1, _REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS:
                raise
            time.sleep(_REPLACE_DELAY_S)


def file_hash(path: Path) -> str | None:
    """sha256 hex digest of the file's bytes, or None if it does not exist."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _make_yaml() -> YAML:
    # Matches the house style of config.yaml: `key:` then `  - item`.
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096  # never re-wrap long lines or comments
    return yaml


# ── Comment bookkeeping ────────────────────────────────────────────────────
# ruamel stores the comment lines that follow an entry on the *last* scalar
# of that entry (recursively). Removing or appending entries would otherwise
# drop or displace comments that belong to the lines below.


def _trailing_slot(node: Any, key: Any) -> tuple[Any, Any, int]:
    """Locate (container, key, slot) holding the comment after `node[key]`."""
    while True:
        value = node[key]
        if isinstance(value, CommentedMap) and len(value):
            node, key = value, list(value.keys())[-1]
        elif isinstance(value, CommentedSeq) and len(value):
            node, key = value, len(value) - 1
        else:
            slot = _SEQ_TRAILING if isinstance(node, CommentedSeq) else _MAP_TRAILING
            return node, key, slot


def _take_following_lines(node: Any, key: Any) -> str:
    """Detach and return the comment lines after `node[key]`'s own line.

    The end-of-line part (inline comment or bare newline) stays in place.
    """
    container, k, slot = _trailing_slot(node, key)
    entry = container.ca.items.get(k)
    token = entry[slot] if entry and len(entry) > slot else None
    if not isinstance(token, CommentToken):
        return ""
    head, sep, rest = token.value.partition("\n")
    if not sep or not rest:
        return ""
    token.value = head + "\n"
    return rest


def _append_following_lines(node: Any, key: Any, rest: str) -> None:
    """Attach comment lines `rest` after `node[key]`'s subtree."""
    if not rest:
        return
    container, k, slot = _trailing_slot(node, key)
    entry = container.ca.items.setdefault(k, [None, None, None, None])
    token = entry[slot]
    if isinstance(token, CommentToken):
        token.value = token.value + rest
    else:
        entry[slot] = CommentToken("\n" + rest, CommentMark(0), None)


def _to_commented(value: Any) -> Any:
    """Convert plain dicts/lists (recursively) to ruamel's commented types.

    Comment bookkeeping can only reach inside commented containers; a plain
    list would get the moved comment lines between its key and its items.
    """
    if isinstance(value, dict) and not isinstance(value, CommentedMap):
        return CommentedMap((k, _to_commented(v)) for k, v in value.items())
    if isinstance(value, CommentedMap):
        for k in list(value.keys()):
            value[k] = _to_commented(value[k])
        return value
    if isinstance(value, (list, tuple)) and not isinstance(value, CommentedSeq):
        return CommentedSeq(_to_commented(v) for v in value)
    if isinstance(value, CommentedSeq):
        for i, v in enumerate(value):
            value[i] = _to_commented(v)
        return value
    return value


# ── List blocks (text level) ───────────────────────────────────────────────
# Toggling list entries is done on the serialized text, not the ruamel tree:
# a disabled entry is a comment line `# - name`, which the tree cannot model.

_NAME = r"[A-Za-z_][A-Za-z0-9_.\-]*"
_ITEM_NAME_RE = re.compile(_NAME)
# Optional matching quotes around the name: `- bash`, `- "bash"`, `- 'bash'`.
_ITEM = rf"""(?P<q>["']?)(?P<name>{_NAME})(?P=q)(?:\s+#.*|\s*)$"""
_ACTIVE_RE = re.compile(rf"^(?P<indent> *)- {_ITEM}")
_COMMENTED_RE = re.compile(rf"^(?P<indent> *)#\s*- {_ITEM}")
_NULL_VALUES = {"", "null", "Null", "NULL", "~"}


def _uncomment_entry(line: str) -> str:
    indent = len(line) - len(line.lstrip(" "))
    # Drop the '#' and the whitespace after it: the dash lands at the '#'
    # column, so `#   - b` cannot turn into a continuation of the item above.
    return line[:indent] + line[indent + 1 :].lstrip(" \t")


class _ListBlock:
    """Lines of a top-level `key:` block: from the key line to the next
    top-level key (column-0 comments and blank lines in between included)."""

    def __init__(self, lines: list[str], start: int, key: str, value: str, comment: str):
        self.start = start
        self.key = key
        self.comment = comment  # inline comment of the key line, with leading space
        self.null_value = value in _NULL_VALUES and value != ""
        self.flow = value not in _NULL_VALUES  # `[a, b]` or another non-block value
        end = start + 1
        while end < len(lines):
            line = lines[end]
            if line == "" or line[0] in " \t#" or line == "-" or line.startswith("- "):
                end += 1
            else:
                break
        self.end = end

        active: list[tuple[int, str, str]] = []
        commented: list[tuple[int, str, str]] = []
        if not self.flow:
            for i in range(start + 1, end):
                if m := _ACTIVE_RE.match(lines[i]):
                    active.append((i, m["name"], m["indent"]))
                elif m := _COMMENTED_RE.match(lines[i]):
                    commented.append((i, m["name"], m["indent"]))
        if active:
            self.item_indent = active[0][2]
        elif commented:
            self.item_indent = commented[0][2]
        else:
            self.item_indent = "  "
        # A `# - x` at another indent (e.g. column 0 after the block)
        # belongs elsewhere.
        commented = [c for c in commented if c[2] == self.item_indent]
        flagged = [(i, n, True) for i, n, _ in active] + [
            (i, n, False) for i, n, _ in commented
        ]
        self.entries: list[tuple[int, str, bool]] = sorted(flagged)

        if self.entries:
            self.insert_at = self.entries[-1][0] + 1
        else:
            # After the key line and its indented comment continuation lines.
            at = start + 1
            while at < end and lines[at][:1] in (" ", "\t") and lines[at].lstrip().startswith("#"):
                at += 1
            self.insert_at = at

    @classmethod
    def find(cls, lines: list[str], key: str) -> _ListBlock | None:
        pattern = re.compile(rf"^{re.escape(key)}\s*:(?=\s|$)(.*)$")
        for i, line in enumerate(lines):
            m = pattern.match(line)
            if m:
                vm = re.match(r"^\s*(.*?)(\s*#.*)?$", m.group(1))
                assert vm is not None
                return cls(lines, i, key, vm.group(1), vm.group(2) or "")
        return None

    def key_line_without_value(self) -> str:
        return f"{self.key}:{self.comment}"


class ConfigDocument:
    """A round-trip editable config.yaml bound to a path and a base hash."""

    def __init__(
        self,
        data: CommentedMap,
        path: Path,
        base_hash: str | None,
        *,
        prefix: str = "",
        newline: str = "\n",
    ) -> None:
        self._data = data
        self._prefix = prefix  # comment-only text when the YAML had no content
        self._newline = newline
        self.path = Path(path)
        self.base_hash = base_hash

    # ── Construction ──

    @classmethod
    def load(cls, path: Path) -> ConfigDocument:
        """Load `path`; a missing file yields an empty document (base_hash None)."""
        path = Path(path)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return cls(CommentedMap(), path, None)
        base_hash = hashlib.sha256(raw).hexdigest()
        newline = "\r\n" if b"\r\n" in raw else "\n"
        text = raw.decode("utf-8").replace("\r\n", "\n")
        doc = cls.from_text(text, path, base_hash)
        doc._newline = newline
        return doc

    @classmethod
    def from_text(cls, text: str, path: Path, base_hash: str | None) -> ConfigDocument:
        """Parse `text`; raise ConfigParseError on invalid YAML or non-mapping root."""
        text = text.replace("\r\n", "\n")
        try:
            data = _make_yaml().load(text)
        except MarkedYAMLError as exc:
            mark = exc.problem_mark or exc.context_mark
            line = mark.line + 1 if mark is not None else None
            message = exc.problem or exc.context or str(exc)
            raise ConfigParseError(str(message), line) from exc
        except YAMLError as exc:
            raise ConfigParseError(str(exc)) from exc
        prefix = ""
        if data is None:
            data = CommentedMap()
            if text.strip():
                prefix = text if text.endswith("\n") else text + "\n"
        elif not isinstance(data, CommentedMap):
            raise ConfigParseError(
                f"Top level must be a mapping, got {type(data).__name__}.", 1
            )
        return cls(data, path, base_hash, prefix=prefix)

    # ── Serialization ──

    def text(self) -> str:
        """Round-trip serialization with LF line endings."""
        if not len(self._data):
            return self._prefix
        buf = io.StringIO()
        _make_yaml().dump(self._data, buf)
        return self._prefix + buf.getvalue()

    # ── Access ──

    def get(self, key: str, default: Any = None) -> Any:
        """Dotted-key lookup, e.g. ``"services.message_board.url"``."""
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        """Dotted-key assignment; creates intermediate maps. ``None`` deletes.

        Deleting the last key of a nested map also removes that (now empty)
        map from its parent, recursively; comment lines following the removed
        block are kept.

        Replacing a container value (map or list) with another value does not
        preserve the comments inside or after the old container. To toggle
        list entries, use the list-item helpers instead.
        """
        *parents, leaf = key.split(".")
        node: CommentedMap = self._data
        chain: list[tuple[CommentedMap, str]] = []  # (container, key) per level
        for i, part in enumerate(parents):
            child = node.get(part)
            if isinstance(child, CommentedMap):
                chain.append((node, part))
                node = child
                continue
            if child is not None:
                raise TypeError(
                    f"Cannot set {key!r}: {'.'.join(parents[: i + 1])!r} is not a mapping."
                )
            if value is None:
                return  # deleting below a missing branch is a no-op
            # Build the missing branch whole, then attach it in one step so
            # comment bookkeeping sees its final shape.
            subtree: Any = value
            for name in reversed([*parents[i + 1 :], leaf]):
                subtree = CommentedMap([(name, subtree)])
            self._assign(node, part, subtree)
            return

        if value is None:
            if leaf not in node:
                return
            # An emptied nested map would serialize as `{}` (and ruamel emits
            # invalid YAML when it carries comments), so remove the highest
            # map that would become empty. Deleting it in one step lets
            # `_delete` carry the block's following comment lines over.
            while chain and len(node) == 1:
                node, leaf = chain.pop()
            self._delete(node, leaf)
        else:
            self._assign(node, leaf, value)

    # ── List items (comment toggling) ──

    def list_items(self, key: str) -> list[tuple[str, bool]]:
        """Ordered `(name, enabled)` entries of the top-level sequence `key`.

        Commented-out entries (`# - name ...`) inside the block count as
        disabled. Section headers and other comments are not entries. A
        missing, empty or null key yields ``[]``. A flow-style list
        (``key: [a, b]``) is reported from its parsed value, all enabled.
        """
        block = _ListBlock.find(self.text().split("\n"), key)
        if block is None:
            return []
        if block.flow:
            value = self.get(key)
            return [(str(v), True) for v in value] if isinstance(value, list) else []
        return [(name, enabled) for _, name, enabled in block.entries]

    def set_item_enabled(self, key: str, name: str, enabled: bool) -> None:
        """Enable/disable `name` in the top-level sequence `key` via comments.

        Disabling rewrites ``  - name   # note`` to ``  # - name   # note``;
        enabling reverses that in place, or appends ``- name`` at the end of
        the block (creating ``key:`` if absent). No-op if already in the
        requested state. Raises ValueError for flow-style lists or a name that
        is not a plain identifier.
        """
        if not _ITEM_NAME_RE.fullmatch(name):
            raise ValueError(f"Not a valid list item name: {name!r}")
        lines = self.text().split("\n")  # text() ends with "\n" -> last is ""
        block = _ListBlock.find(lines, key)
        states = [] if block is None else [
            (i, enabled_) for i, n, enabled_ in block.entries if n == name
        ]
        if block is not None and block.flow:
            value = self.get(key)
            if (isinstance(value, list) and name in value) == enabled:
                return
            raise ValueError(
                f"Cannot toggle items of {key!r}: its value is not a block list "
                "(flow-style lists like [a, b] and scalar values are not "
                "supported); rewrite it as a block list."
            )

        if enabled:
            if any(e for _, e in states):
                return
            if states:  # uncomment the first commented occurrence
                i = states[0][0]
                lines[i] = _uncomment_entry(lines[i])
            elif block is None:
                if lines and lines[-1] == "":
                    lines.pop()
                lines += [f"{key}:", f"  - {name}", ""]
            else:
                if block.null_value:
                    lines[block.start] = block.key_line_without_value()
                lines.insert(block.insert_at, f"{block.item_indent}- {name}")
        else:
            active = [i for i, e in states if e]
            if not active:
                return
            for i in active:
                indent = len(lines[i]) - len(lines[i].lstrip(" "))
                lines[i] = lines[i][:indent] + "# " + lines[i][indent:]
        self.replace_text("\n".join(lines))

    def replace_text(self, text: str) -> None:
        """Re-parse `text` into this document, keeping path, base_hash and line endings.

        Raises ConfigParseError on invalid text; the document is then unchanged.
        """
        new = ConfigDocument.from_text(text, self.path, self.base_hash)
        self._data = new._data
        self._prefix = new._prefix

    # ── Persistence ──

    def save(self, expected_hash: str | None = _UNSET, force: bool = False) -> str:
        """Atomically write the document; return and record the new hash.

        Raises ConfigConflictError if the on-disk hash differs from
        `expected_hash` (default: `self.base_hash`) and `force` is False.
        """
        if expected_hash is _UNSET:
            expected_hash = self.base_hash
        if not force and file_hash(self.path) != expected_hash:
            raise ConfigConflictError(f"{self.path} changed on disk since it was loaded.")
        payload = self.text().replace("\n", self._newline).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".yaml.tmp")
        try:
            tmp.write_bytes(payload)
            _replace_with_retry(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        self.base_hash = hashlib.sha256(payload).hexdigest()
        return self.base_hash

    # ── Internals ──

    @staticmethod
    def _assign(node: CommentedMap, key: str, value: Any) -> None:
        value = _to_commented(value)
        if key in node:
            old = node[key]
            # Keep the original quoting style for string replacements.
            if type(value) is str and isinstance(
                old, (DoubleQuotedScalarString, SingleQuotedScalarString)
            ):
                value = type(old)(value)
            node[key] = value  # comments live in node.ca, keyed by `key`
            return
        last = list(node.keys())[-1] if len(node) else None
        # Lines after the old last entry belong below the block; keep them there.
        rest = _take_following_lines(node, last) if last is not None else ""
        node[key] = value
        _append_following_lines(node, key, rest)

    @staticmethod
    def _delete(node: CommentedMap, key: str) -> None:
        if key not in node:
            return
        keys = list(node.keys())
        idx = keys.index(key)
        rest = _take_following_lines(node, key)
        del node[key]
        node.ca.items.pop(key, None)
        if not rest:
            return
        if idx > 0:
            _append_following_lines(node, keys[idx - 1], rest)
        else:
            # No previous sibling: the lines precede the (new) first entry.
            pre = node.ca.comment
            if pre is None:
                node.ca.comment = [None, []]
                pre = node.ca.comment
            if pre[1] is None:
                pre[1] = []
            pre[1].append(CommentToken(rest, CommentMark(0), None))
