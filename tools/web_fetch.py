import re

from agent.base_tool import BaseTool

_MAX_CHARS = 8000
_STRIP_TAGS = {"script", "style", "nav", "footer", "head"}


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Fetch a URL and return its readable text content. "
        "Strips HTML tags, scripts, and navigation elements. "
        "Provide a prompt describing what you are looking for on the page."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "prompt": {"type": "string", "description": "What to look for on the page"},
        },
        "required": ["url", "prompt"],
    }

    def run(self, url: str, prompt: str) -> str:
        try:
            import httpx
        except ImportError:
            return "Error: httpx package not installed. Run: pip install httpx"
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "Error: beautifulsoup4 package not installed. Run: pip install beautifulsoup4"

        # Upgrade http → https except for localhost
        if url.startswith("http://") and "localhost" not in url:
            url = "https://" + url[7:]

        try:
            resp = httpx.get(
                url,
                follow_redirects=True,
                timeout=20,
                headers={"User-Agent": "dagi/0.1"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} fetching {url}"
        except Exception as e:
            return f"Error: failed to fetch {url}: {e}"

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all(_STRIP_TAGS):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        # Collapse runs of blank lines to a single blank line
        text = re.sub(r"\n{3,}", "\n\n", text)

        header = f"[Fetched: {url}]\n[Looking for: {prompt}]\n\n"
        full = header + text

        if len(full) > _MAX_CHARS:
            full = full[:_MAX_CHARS] + "\n[truncated]"

        return full
