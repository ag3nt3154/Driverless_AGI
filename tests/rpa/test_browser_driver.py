"""tests/rpa/test_browser_driver.py — FirefoxDriver (Subtask 8).

The missing-binary test needs no browser and always runs. Every other test
drives a real (headless) Firefox through geckodriver and is marked
`desktop` (skipped unless DAGI_DESKTOP_TESTS=1; run unsandboxed).
"""
from __future__ import annotations

import functools
import http.server
import threading
import time
from pathlib import Path

import pytest

from rpa import RpaError
from rpa.drivers.browser import FirefoxDriver
from rpa.resolver import generate_locators, resolve

FIXTURE_SITE = Path(__file__).parent / "fixtures" / "site"


def test_missing_binaries_raise_clear_rpa_error(tmp_path):
    """Unit test (no browser): a fake conda prefix with no Firefox/geckodriver."""
    driver = FirefoxDriver(profile_dir=tmp_path / "profile", prefix=tmp_path / "no-such-env")
    with pytest.raises(RpaError, match="conda install"):
        driver.roots()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@pytest.fixture
def site_url():
    handler = functools.partial(_QuietHandler, directory=str(FIXTURE_SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def driver_factory(tmp_path):
    """Builds FirefoxDrivers sharing one profile dir; always quits them at teardown."""
    profile_dir = tmp_path / "profile"
    created: list[FirefoxDriver] = []

    def make() -> FirefoxDriver:
        d = FirefoxDriver(profile_dir=profile_dir, headless=True)
        created.append(d)
        return d

    yield make
    for d in created:
        d.quit()


@pytest.mark.desktop
def test_outline_names_file_input_and_secures_password(site_url, driver_factory):
    driver = driver_factory()
    root = driver.launch(site_url)
    outline = driver.outline(root)

    file_elements = [e for e in outline.elements if e.role == "file"]
    assert len(file_elements) == 1
    assert file_elements[0].name  # named via aria-label/label/name-attr/"Browse…" fallback

    pw_elements = [e for e in outline.elements if e.role == "password"]
    assert len(pw_elements) == 1
    assert pw_elements[0].value == "[secure]"
    assert pw_elements[0].secure is True


@pytest.mark.desktop
def test_canary_in_password_never_in_outline(site_url, driver_factory):
    driver = driver_factory()
    root = driver.launch(site_url)
    pw = next(e for e in driver.outline(root).elements if e.role == "password")
    driver.act(root, pw, "type", "CANARY-s3cret")
    for elem in driver.outline(root).elements:
        assert "CANARY" not in (elem.value or "")
        assert "CANARY" not in (elem.name or "")


@pytest.mark.desktop
def test_find_two_ok_buttons(site_url, driver_factory):
    driver = driver_factory()
    root = driver.launch(site_url)
    matches = driver.find(root, {"aria": {"role": "button", "name": "OK"}})
    assert len(matches) == 2


@pytest.mark.desktop
def test_upload_sets_upname(site_url, driver_factory, tmp_path):
    driver = driver_factory()
    root = driver.launch(site_url)
    upload_file = tmp_path / "upload_me.csv"
    upload_file.write_text("a,b\n1,2\n")
    file_element = next(e for e in driver.outline(root).elements if e.role == "file")
    driver.act(root, file_element, "upload", str(upload_file))

    # #upname is a plain <p> with no ARIA role, so it never appears in the
    # outline itself (by design — the outline only lists elements that have a
    # role); read it straight from Selenium, like the acceptance criterion
    # ("upload sets #upname") describes the page, not the outline.
    from selenium.webdriver.common.by import By

    deadline = time.time() + 3
    upname_value = None
    while time.time() < deadline:
        text = driver._driver.find_element(By.ID, "upname").text
        if text:
            upname_value = text
            break
        time.sleep(0.1)
    assert upname_value == f"uploaded:{upload_file.name}"


@pytest.mark.desktop
def test_profile_persists_across_restart(site_url, driver_factory):
    d1 = driver_factory()
    root1 = d1.launch(site_url)
    d1.act(root1, next(e for e in d1.outline(root1).elements if e.role == "textbox" and e.name == "Comment"), "focus")
    d1._driver.execute_script("localStorage.setItem('s0', 'persisted')")
    d1.quit()

    d2 = driver_factory()
    root2 = d2.launch(site_url)
    value = d2._driver.execute_script("return localStorage.getItem('s0')")
    assert value == "persisted"


@pytest.mark.desktop
def test_resolver_round_trip_for_export_csv_button(site_url, driver_factory):
    driver = driver_factory()
    root = driver.launch(site_url)
    export_button = next(e for e in driver.outline(root).elements if e.name == "Export CSV")

    locators = generate_locators(driver, root, export_button)
    assert locators[0] == {"css": '[data-testid="export-btn"]'}

    resolution = resolve(driver, root, locators)
    assert resolution.rung_index == 0
    assert resolution.element.name == "Export CSV"


@pytest.mark.desktop
def test_act_refuses_when_the_page_changed_under_the_element(site_url, driver_factory):
    """An element seen in an earlier outline must not be acted on once another node
    has taken its index: act raises WrongElement and clicks nothing."""
    from rpa.drivers.base import WrongElement

    driver = driver_factory()
    root = driver.launch(site_url)
    first_ok = driver.find(root, {"aria": {"role": "button", "name": "OK"}})[0]
    driver._driver.execute_script(
        "const b = document.createElement('button'); b.textContent = 'Inserted';"
        "b.onclick = () => document.title = 'clicked-inserted';"
        "document.body.insertBefore(b, document.body.firstChild);"
    )
    with pytest.raises(WrongElement):
        driver.act(root, first_ok, "click")
    assert driver._driver.title != "clicked-inserted"


@pytest.mark.desktop
def test_key_chords_work_in_the_browser(site_url, driver_factory):
    driver = driver_factory()
    root = driver.launch(site_url)
    comment = next(e for e in driver.outline(root).elements if e.name == "Comment")
    driver.act(root, comment, "type", "abc")
    driver.act(root, comment, "key", "ctrl+a")
    driver.act(root, comment, "key", "backspace")
    assert driver._driver.find_element("name", "comment").get_attribute("value") == ""


@pytest.mark.desktop
def test_pids_cover_the_running_firefox(site_url, driver_factory):
    driver = driver_factory()
    assert driver.pids() == set()
    driver.launch(site_url)
    assert driver.pids()


@pytest.mark.desktop
def test_close_root_closes_tabs_and_the_last_close_restarts_cleanly(site_url, driver_factory):
    from rpa import RpaError
    driver = driver_factory()
    first = driver.launch(site_url)
    second = driver.launch(site_url)
    driver.close_root(second)
    assert second.id not in {r.id for r in driver.roots()}
    for root in driver.roots():
        driver.close_root(root)
    again = driver.launch(site_url)  # a dead session would raise here
    assert again.url.startswith("http://127.0.0.1")
    with pytest.raises(RpaError):
        driver.outline(first)  # closed tab: a clear RpaError, not a raw Selenium error


@pytest.mark.desktop
def test_first_launch_reuses_the_start_tab_so_closing_it_closes_the_window(site_url, driver_factory):
    import time
    driver = driver_factory()
    root = driver.launch(site_url)
    assert [r.id for r in driver.roots()] == [root.id]  # no leftover about:blank tab
    t0 = time.monotonic()
    driver.close_root(root)
    assert not driver.started  # the window (and session) is gone
    assert time.monotonic() - t0 < 10
