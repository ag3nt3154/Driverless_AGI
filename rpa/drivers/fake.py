"""rpa/drivers/fake.py — FakeDriver: an in-memory Driver for unit tests.

Built from a plain dict/list tree so tests can describe a UI without touching
real UIA or a browser. The tree may be mutated between calls (append/remove
children, change a `value`) to simulate the UI changing underneath a test.
"""
from __future__ import annotations

import re
from typing import Any

from rpa import RpaError
from rpa.drivers.base import WrongElement
from rpa.model import Element, Locator, Outline, Root, validate_locator

# Default window size used by `screenshot` when none was given for a root.
_DEFAULT_SIZE = (800, 600)


class FakeDriver:
    """Driver backed by `{root_id: [node, ...]}` trees of plain dicts.

    Node keys: role, name, automation_id, value, secure, interactive, bbox,
    css, children (list of nodes, same shape).
    """

    def __init__(
        self,
        roots: dict[str, Root],
        trees: dict[str, list[dict[str, Any]]],
        *,
        sizes: dict[str, tuple[int, int]] | None = None,
        lock_actions: set[str] | None = None,
    ) -> None:
        self._roots = dict(roots)
        self._trees = trees  # kept by reference so callers can mutate it
        self._sizes = sizes or {}
        self._lock_actions = lock_actions or set()
        self.acts: list[tuple[str, int, str, str | None]] = []
        # index -> (root_id, node dict), rebuilt on every outline() call
        self._nodes_by_index: dict[str, dict[int, dict[str, Any]]] = {}

    # -- Driver protocol -------------------------------------------------

    def roots(self) -> list[Root]:
        return list(self._roots.values())

    def outline(self, root: Root, *, query: str | None = None, depth: int | None = None) -> Outline:
        elements: list[Element] = []
        nodes_by_index: dict[int, dict[str, Any]] = {}
        counter = [0]

        def walk(nodes: list[dict[str, Any]], path: tuple[str, ...], level: int) -> None:
            for node in nodes:
                if depth is not None and level > depth:
                    continue
                index = counter[0]
                counter[0] += 1
                children = node.get("children", [])
                secure = bool(node.get("secure", False))
                value = "[secure]" if secure else node.get("value")
                element = Element(
                    index=index,
                    role=node.get("role", ""),
                    name=node.get("name", ""),
                    automation_id=node.get("automation_id"),
                    bbox=tuple(node.get("bbox", (0, 0, 10, 10))),
                    value=value,
                    secure=secure,
                    interactive=bool(node.get("interactive", not children)),
                    path=path,
                )
                nodes_by_index[index] = node
                if query is None or query.lower() in element.name.lower():
                    elements.append(element)
                if children:
                    child_path = path + (f"{element.role}:{element.name}",)
                    walk(children, child_path, level + 1)

        walk(self._trees.get(root.id, []), (), 0)
        self._nodes_by_index[root.id] = nodes_by_index
        return Outline(root=root, elements=elements)

    def find(self, root: Root, locator: Locator) -> list[Element]:
        validate_locator(locator)
        kind = next(iter(locator))
        elements = self.outline(root).elements
        if kind == "uia":
            return [e for e in elements if self._match_uia(e, locator["uia"])]
        if kind == "css":
            return [e for e in elements if self._match_css(root, e, locator["css"])]
        if kind == "aria":
            return [e for e in elements if self._match_aria(e, locator["aria"])]
        if kind == "coords":
            point = locator["coords"]
            return [e for e in elements if self._contains(e.bbox, point["x"], point["y"])]
        # ocr/image: not resolved by the fake driver in v1.
        return []

    def close_root(self, root: Root) -> None:
        self.acts.append((root.id, None, "close_window", None))
        for key, r in list(self._roots.items()):
            if r.id == root.id:
                del self._roots[key]

    def act(self, root: Root, element: Element, action: str, value: str | None = None) -> None:
        live = next((e for e in self.outline(root).elements if e.index == element.index), None)
        if live is None or (live.role, live.name, live.automation_id, live.path) != (
            element.role, element.name, element.automation_id, element.path,
        ):
            raise WrongElement(f"FakeDriver.act: {element.role} {element.name!r} is no longer at index {element.index}")
        node = self._nodes_by_index.get(root.id, {}).get(element.index)
        secure = element.secure or bool(node and node.get("secure"))
        self.acts.append((root.id, element.index, action, "[secure]" if secure and value is not None else value))
        if node is not None and action in ("set_value", "type") and value is not None and not node.get("secure"):
            node["value"] = value

    def screenshot(self, root: Root, region: tuple[int, int, int, int] | None = None):
        from PIL import Image

        width, height = self._sizes.get(root.id, _DEFAULT_SIZE)
        if region is not None:
            x0, y0, x1, y1 = region
            width, height = max(1, x1 - x0), max(1, y1 - y0)
        return Image.new("RGB", (width, height))

    def needs_desktop_lock(self, action: str) -> bool:
        return action in self._lock_actions

    def needs_desktop_lock_to_observe(self, root: Root) -> bool:
        return False

    def launch(self, target: str) -> Root:
        if target in self._roots:
            return self._roots[target]
        raise RpaError(f"FakeDriver.launch: unknown target {target!r} (add it to the roots/trees given to FakeDriver)")

    # -- matching helpers -------------------------------------------------

    @staticmethod
    def _contains(bbox: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    @staticmethod
    def _match_uia(element: Element, spec: dict[str, Any]) -> bool:
        if "automation_id" in spec and element.automation_id != spec["automation_id"]:
            return False
        if "role" in spec and element.role != spec["role"]:
            return False
        if "name" in spec and element.name != spec["name"]:
            return False
        if "name_re" in spec and not re.search(spec["name_re"], element.name):
            return False
        within = spec.get("within")
        if within is not None:
            wanted = [within] if isinstance(within, str) else list(within)
            if not all(w in element.path for w in wanted):
                return False
        return True

    def _match_css(self, root: Root, element: Element, css: str) -> bool:
        node = self._nodes_by_index.get(root.id, {}).get(element.index, {})
        target = css[1:] if css.startswith("#") else css
        return node.get("css") == css or element.automation_id in (css, target)

    @staticmethod
    def _match_aria(element: Element, spec: dict[str, Any]) -> bool:
        if "role" in spec and element.role.lower() != spec["role"].lower():
            return False
        if "name" in spec and element.name != spec["name"]:
            return False
        return True
