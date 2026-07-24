from agent.base_tool import BaseTool


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for current information using DuckDuckGo. "
        "Returns up to 8 results with title, URL, and snippet. "
        "Use allowed_domains to restrict results to specific sites, or "
        "blocked_domains to exclude them."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (min 2 characters)",
                "minLength": 2,
            },
            "allowed_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only return results from these domains (optional)",
            },
            "blocked_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exclude results from these domains (optional)",
            },
        },
        "required": ["query"],
    }

    def run(
        self,
        query: str,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> str:
        try:
            from ddgs import DDGS
        except ImportError:
            return "Error: ddgs package not installed. Run: pip install ddgs"

        try:
            raw = DDGS().text(query, max_results=20)
        except Exception as e:
            return f"Error: DuckDuckGo search failed: {e}"

        results = []
        for r in raw:
            url = r.get("href", "")
            if allowed_domains and not any(d in url for d in allowed_domains):
                continue
            if blocked_domains and any(d in url for d in blocked_domains):
                continue
            results.append(r)
            if len(results) >= 8:
                break

        if not results:
            return "[no results]"

        lines = []
        for r in results:
            lines.append(f"{r.get('title', '(no title)')} | {r.get('href', '')}")
            if r.get("body"):
                lines.append(r["body"])
            lines.append("")

        return "\n".join(lines).strip()
