"""rpa/drivers/browser.py — FirefoxDriver: the Driver implementation for Firefox tabs.

Uses stock conda-forge Firefox via geckodriver + Selenium (D9). dagi injects its
own outline.js (Firefox's WebDriver-computed aria_role/accessible_name are empty
for date/password inputs — S0 finding) instead of relying on the browser's own
accessibility tree.

WebElement <-> Element mapping: `outline.js` tags every element it includes in
its output with `data-dagi-i="<index>"` as a side effect of the walk. `find()`
for a `css` locator re-runs the outline (refreshing the tags), then maps each
Selenium `find_elements` hit back to an outline `Element` by reading that
attribute and looking the index up in the same outline — never by re-matching
bbox/role, which breaks under duplicates (e.g. two identical "OK" buttons).
`aria` locators match directly against the fresh outline's role/name/path.
`act()` re-runs the outline, locates the live WebElement by the `Element`'s
`automation_id` CSS token (when it matches exactly one node) or else by its
index, and then checks that the live element's role, name and automation_id
equal the given `Element`'s; any difference raises `WrongElement` instead of
acting (the DOM may change between the caller's rebind and this act).

`roots()` switches to each tab to read its title/url and then switches back.
iframes and shadow DOM are not traversed (v1).
"""
from __future__ import annotations

import functools
import io
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psutil
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import Select

from rpa import RpaError
from rpa.drivers.base import WrongElement
from rpa.keys import parse_chord
from rpa.model import Element, Locator, Outline, Root, validate_locator

_OUTLINE_JS = (Path(__file__).parent / "outline.js").read_text(encoding="utf-8")

_CONDA_INSTALL_LINE = "conda install -n dagi -c conda-forge firefox=157.0.1 geckodriver=0.37.1"

# rpa/keys.py chord names -> selenium Keys (D3's ui_act `key`).
_NAMED_KEYS = {
    "enter": Keys.ENTER, "tab": Keys.TAB, "escape": Keys.ESCAPE, "esc": Keys.ESCAPE,
    "backspace": Keys.BACKSPACE, "delete": Keys.DELETE, "insert": Keys.INSERT, "space": Keys.SPACE,
    "home": Keys.HOME, "end": Keys.END, "pageup": Keys.PAGE_UP, "pagedown": Keys.PAGE_DOWN,
    "up": Keys.ARROW_UP, "down": Keys.ARROW_DOWN, "left": Keys.ARROW_LEFT, "right": Keys.ARROW_RIGHT,
    **{f"f{n}": getattr(Keys, f"F{n}") for n in range(1, 13)},
}
_MODIFIER_KEYS = {"ctrl": Keys.CONTROL, "shift": Keys.SHIFT, "alt": Keys.ALT, "win": Keys.META}


def _named_key(key: str) -> str:
    return _NAMED_KEYS.get(key, key)



def _wd_guard(method):
    """Selenium/WebDriver errors (e.g. a tab that was closed) become RpaError."""
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except WebDriverException as exc:
            raise RpaError(f"Firefox call failed ({method.__name__}): {exc.msg or exc}") from exc
    return wrapper


class FirefoxDriver:
    """`Driver` for Firefox tabs through geckodriver + Selenium."""

    def __init__(self, profile_dir: Path, headless: bool = False, *, prefix: Path | str | None = None) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        # `prefix` is injectable so a unit test can point at a fake conda env
        # and exercise the "missing binaries" error without touching the real one.
        self._prefix = Path(prefix) if prefix is not None else Path(sys.prefix)
        self._driver = None

    # -- lifecycle --------------------------------------------------------

    def _ensure_started(self) -> None:
        if self._driver is not None:
            return
        firefox_path = self._prefix / "Library" / "bin" / "firefox.exe"
        gecko_path = self._prefix / "Scripts" / "geckodriver.exe"
        missing = [p for p in (firefox_path, gecko_path) if not p.exists()]
        if missing:
            raise RpaError(
                "Firefox/geckodriver not found: " + ", ".join(str(p) for p in missing) + ". "
                f"Install into the dagi env: {_CONDA_INSTALL_LINE}"
            )
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = Options()
        options.binary_location = str(firefox_path)
        options.add_argument("-profile")
        options.add_argument(str(self.profile_dir))
        if self.headless:
            options.add_argument("-headless")
        self._driver = webdriver.Firefox(options=options, service=Service(str(gecko_path)))

    def pids(self) -> set[int]:
        """PIDs of this driver's Firefox (main + content processes); empty if not started."""
        if self._driver is None:
            return set()
        pid = self._driver.capabilities.get("moz:processID")
        if not pid:
            return set()
        try:
            main = psutil.Process(pid)
            return {pid, *(child.pid for child in main.children(recursive=True))}
        except psutil.Error:
            return {pid}

    @property
    def started(self) -> bool:
        """True while a Firefox session is running (the driver starts it lazily)."""
        return self._driver is not None

    def quit(self) -> None:
        """Close the browser and release the underlying geckodriver session."""
        if self._driver is not None:
            try:
                self._driver.quit()
            except WebDriverException:
                pass  # the session already ended (e.g. its last tab was closed)
            finally:
                self._driver = None

    close = quit

    # -- Driver protocol ---------------------------------------------------

    @_wd_guard
    def roots(self) -> list[Root]:
        self._ensure_started()
        current = self._driver.current_window_handle
        result = []
        for handle in self._driver.window_handles:
            self._driver.switch_to.window(handle)
            url = self._driver.current_url
            result.append(
                Root(id=handle, kind="browser", title=self._driver.title, pid=None, url=url, app=self._origin(url))
            )
        if current in self._driver.window_handles:
            self._driver.switch_to.window(current)
        return result

    @_wd_guard
    def outline(self, root: Root, *, query: str | None = None, depth: int | None = None) -> Outline:
        # `depth` is accepted for the Driver protocol; the DOM walk is flat (v1).
        self._ensure_started()
        self._switch_to(root)
        raw = self._driver.execute_script(_OUTLINE_JS)
        elements = [self._to_element(n) for n in raw]
        if query:
            elements = [e for e in elements if query.lower() in e.name.lower()]
        return Outline(root=root, elements=elements)

    @_wd_guard
    def find(self, root: Root, locator: Locator) -> list[Element]:
        validate_locator(locator)
        kind = next(iter(locator))
        if kind in ("ocr", "image"):
            return []
        outline = self.outline(root)  # refresh + re-tag before matching
        if kind == "css":
            by_index = {e.index: e for e in outline.elements}
            found = []
            for we in self._driver.find_elements(By.CSS_SELECTOR, locator["css"]):
                tag = we.get_attribute("data-dagi-i")
                if tag is None:
                    continue
                el = by_index.get(int(tag))
                if el is not None:
                    found.append(el)
            return found
        if kind == "aria":
            spec = locator["aria"]
            results = []
            for el in outline.elements:
                if spec.get("role") is not None and el.role.lower() != spec["role"].lower():
                    continue
                if "name" in spec and el.name != spec["name"]:
                    continue
                within = spec.get("within")
                if within:
                    wanted = [within] if isinstance(within, str) else list(within)
                    if not all(w in el.path for w in wanted):
                        continue
                results.append(el)
            return results
        if kind == "coords":
            pt = locator["coords"]
            x, y = pt["x"], pt["y"]
            return [e for e in outline.elements if e.bbox[0] <= x <= e.bbox[2] and e.bbox[1] <= y <= e.bbox[3]]
        raise RpaError(f"FirefoxDriver.find: unsupported locator kind {kind!r}")

    @_wd_guard
    def act(self, root: Root, element: Element, action: str, value: str | None = None) -> None:
        self._ensure_started()
        if action == "close_window":
            self.close_root(root)
            return
        we = self._webelement_for(root, element)
        if action == "click":
            we.click()
        elif action == "double_click":
            ActionChains(self._driver).double_click(we).perform()
        elif action == "right_click":
            ActionChains(self._driver).context_click(we).perform()
        elif action == "set_value":
            we.clear()
            if value is not None:
                we.send_keys(value)
        elif action == "type":
            if value is not None:
                we.send_keys(value)
        elif action == "key":
            mods, key = parse_chord(value)
            chain = ActionChains(self._driver).click(we) if mods else None
            if chain is None:
                we.send_keys(_named_key(key))
            else:
                for mod in mods:
                    chain = chain.key_down(_MODIFIER_KEYS[mod])
                chain = chain.send_keys(_named_key(key))
                for mod in reversed(mods):
                    chain = chain.key_up(_MODIFIER_KEYS[mod])
                chain.perform()
        elif action == "scroll":
            if value:
                self._driver.execute_script(
                    "window.scrollBy(arguments[0], arguments[1]);", value.get("dx", 0), value.get("dy", 0)
                )
            else:
                self._driver.execute_script("arguments[0].scrollIntoView();", we)
        elif action == "select":
            Select(we).select_by_visible_text(value)
        elif action == "upload":
            we.send_keys(value)
        elif action == "focus":
            self._driver.execute_script("arguments[0].focus();", we)
        else:
            raise RpaError(f"FirefoxDriver.act: unsupported action {action!r}")

    @_wd_guard
    def screenshot(self, root: Root, region: tuple[int, int, int, int] | None = None):
        from PIL import Image

        self._ensure_started()
        self._switch_to(root)
        png = self._driver.get_screenshot_as_png()
        image = Image.open(io.BytesIO(png))
        if region is not None:
            left, top, right, bottom = region  # (left, top, right, bottom), viewport-relative
            if right <= left or bottom <= top:
                raise RpaError(f"FirefoxDriver.screenshot: empty region {region!r} (expects left, top, right, bottom)")
            image = image.crop((left, top, right, bottom))
        return image

    @_wd_guard
    def close_root(self, root: Root) -> None:
        """Close the tab; switch to a remaining one, or end the session if it was the last
        (the next use starts Firefox again instead of failing on a dead session)."""
        self._ensure_started()
        self._switch_to(root)
        self._driver.close()
        try:
            remaining = self._driver.window_handles
        except WebDriverException:  # Firefox ended the session with its last window
            remaining = []
        if remaining:
            self._driver.switch_to.window(remaining[0])
        else:
            self.quit()

    def needs_desktop_lock(self, action: str) -> bool:
        return False  # browser-only (WebDriver) acts never take the desktop lock (D4)

    def needs_desktop_lock_to_observe(self, root: Root) -> bool:
        return False

    @_wd_guard
    def launch(self, target: str) -> Root:
        """Open `target` in a new tab — or in Firefox's empty start tab, so that closing
        dagi's last tab closes the window instead of leaving an about:blank one."""
        self._ensure_started()
        handles = self._driver.window_handles
        if not (len(handles) == 1 and self._driver.current_url == "about:blank"):
            self._driver.switch_to.new_window("tab")
        self._driver.get(target)
        url = self._driver.current_url
        return Root(
            id=self._driver.current_window_handle,
            kind="browser",
            title=self._driver.title,
            pid=None,
            url=url,
            app=self._origin(url),
        )

    # -- helpers ------------------------------------------------------------

    def _switch_to(self, root: Root) -> None:
        if self._driver.current_window_handle != root.id:
            self._driver.switch_to.window(root.id)

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else url

    @staticmethod
    def _to_element(n: dict) -> Element:
        if n.get("id"):
            automation_id = f'#{n["id"]}'
        elif n.get("testid"):
            automation_id = f'[data-testid="{n["testid"]}"]'
        else:
            automation_id = None
        return Element(
            index=n["i"],
            role=n.get("role") or "",
            name=n.get("name") or "",
            automation_id=automation_id,
            bbox=tuple(int(v) for v in n["bbox"]),
            value=n.get("value"),
            secure=bool(n.get("secure")),
            interactive=bool(n.get("interactive")),
            path=tuple(n.get("path") or ()),
        )

    def _webelement_for(self, root: Root, element: Element):
        """The live WebElement for `element`; raises WrongElement if it is not the same element."""
        live = {e.index: e for e in self.outline(root).elements}  # re-tags data-dagi-i
        we = None
        if element.automation_id:
            matches = self._driver.find_elements(By.CSS_SELECTOR, element.automation_id)
            if len(matches) == 1:
                we = matches[0]
        if we is None:
            matches = self._driver.find_elements(By.CSS_SELECTOR, f'[data-dagi-i="{element.index}"]')
            if len(matches) != 1:
                raise WrongElement(
                    f"FirefoxDriver: could not re-locate element index={element.index} "
                    f"role={element.role!r} name={element.name!r}"
                )
            we = matches[0]
        tag = we.get_attribute("data-dagi-i")
        current = live.get(int(tag)) if tag is not None else None
        if current is None or (current.role, current.name, current.automation_id) != (
            element.role, element.name, element.automation_id,
        ):
            raise WrongElement(
                f"FirefoxDriver: the page changed; element {element.role!r} {element.name!r} "
                f"is no longer at index {element.index}"
            )
        return we

