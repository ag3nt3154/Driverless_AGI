"""tools/web_fetch.py — Fetch a URL and return clean Markdown via crawl4ai.

Falls back to httpx + BeautifulSoup plain-text extraction when crawl4ai is
not installed or when the crawl fails.  The public interface is unchanged:
WebFetchTool.run(url, prompt) returns a str.

Async→sync bridge
-----------------
crawl4ai exposes an async API.  We bridge it synchronously using two strategies
chosen at call time:

1. No running event loop in the calling thread  →  asyncio.run() (simplest, safe)
2. A running event loop already exists (e.g. NiceGUI, Jupyter, async test runner)
   →  spin up a fresh event loop in a ThreadPoolExecutor worker thread and block
   on its future.  This avoids the "cannot run nested event loop" RuntimeError.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from agent.base_tool import BaseTool

_MAX_CHARS = 50_000
_STRIP_TAGS = {"script", "style", "nav", "footer", "head"}


def _run_async(coro):
    """Run an async coroutine to completion from synchronous code.

    Handles two scenarios:
    - No running event loop in the current thread: asyncio.run() directly.
    - A running event loop already exists: delegate to a worker thread with its
      own fresh loop and block on the result.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
        # A loop is already running in this thread — delegate to a worker.
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        # No running loop — safe to use asyncio.run() directly.
        return asyncio.run(coro)


async def _fetch_with_crawl4ai(url: str) -> str:
    """Async helper: fetch *url* with crawl4ai and return markdown text."""
    import os
    # Ensure UTF-8 for any console output crawl4ai may emit on Windows.
    os.environ.setdefault("PYTHONUTF8", "1")

    from crawl4ai import AsyncWebCrawler
    from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig

    browser_cfg = BrowserConfig(headless=True, verbose=False)
    run_cfg = CrawlerRunConfig(
        word_count_threshold=10,
        excluded_tags=list(_STRIP_TAGS),
        page_timeout=25_000,   # milliseconds
        verbose=False,
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)

    if not result.success:
        raise RuntimeError(result.error_message or "crawl4ai returned no content")

    # result.markdown is a StringCompatibleMarkdown — behaves like a plain str.
    md = str(result.markdown) if result.markdown else ""

    if not md.strip():
        raise RuntimeError("crawl4ai returned empty markdown")

    return md


def _fetch_with_bs4(url: str) -> str:
    """Fallback: plain-text extraction via httpx + BeautifulSoup."""
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "dagi/0.1"},
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Fetch a URL and return its content as clean Markdown (headings, links, "
        "and code blocks preserved). Falls back to plain text if crawl4ai is not "
        "installed. Provide a prompt describing what you are looking for on the page."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "prompt": {
                "type": "string",
                "description": "What to look for on the page",
            },
        },
        "required": ["url", "prompt"],
    }

    def run(self, url: str, prompt: str) -> str:  # noqa: D401
        # Upgrade http → https except for localhost / loopback
        if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
            url = "https://" + url[7:]

        content: str = ""
        method_used: str = ""
        crawl4ai_error: str | None = None

        # --- Attempt 1: crawl4ai markdown ---
        try:
            import crawl4ai  # noqa: F401  (availability check only)
            try:
                content = _run_async(_fetch_with_crawl4ai(url))
                method_used = "crawl4ai/markdown"
            except Exception as exc:
                crawl4ai_error = str(exc)
        except ImportError:
            crawl4ai_error = "crawl4ai not installed"

        # --- Attempt 2: httpx + BeautifulSoup fallback ---
        if not content:
            try:
                import httpx  # noqa: F401
                from bs4 import BeautifulSoup  # noqa: F401
            except ImportError as e:
                return (
                    f"Error: required package missing ({e}). "
                    "Install crawl4ai or both httpx and beautifulsoup4."
                )
            try:
                content = _fetch_with_bs4(url)
                method_used = "httpx+bs4/plaintext"
                if crawl4ai_error and crawl4ai_error != "crawl4ai not installed":
                    content += (
                        f"\n\n[Note: crawl4ai failed ({crawl4ai_error}); "
                        "plain-text fallback used]"
                    )
            except Exception as exc:
                return f"Error: failed to fetch {url}: {exc}"

        header = f"[Fetched: {url}] [{method_used}]\n[Looking for: {prompt}]\n\n"
        full = header + content

        if len(full) > _MAX_CHARS:
            full = full[:_MAX_CHARS] + "\n\n[truncated]"

        return full
