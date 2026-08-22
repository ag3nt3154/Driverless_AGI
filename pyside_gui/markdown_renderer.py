from __future__ import annotations

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, TextLexer

_FORMATTER = HtmlFormatter(nowrap=True, cssclass="highlight")


def _highlight_code(code: str, lang: str) -> str:
    try:
        lexer = get_lexer_by_name(lang, stripall=True)
    except Exception:
        lexer = TextLexer(stripall=True)
    return highlight(code, lexer, _FORMATTER)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _fence_renderer(tokens, idx, options, env):
    token = tokens[idx]
    lang = token.info.strip() if token.info else ""
    code = token.content
    if lang:
        highlighted = _highlight_code(code, lang)
        return (
            f'<pre><code class="highlight language-{lang}">'
            f"{highlighted}</code></pre>\n"
        )
    return f"<pre><code>{_escape(code)}</code></pre>\n"


_md = MarkdownIt("gfm-like").enable("table").disable("linkify")
# Wrap in lambda to insulate from add_render_rule's internal binding behaviour.
_md.add_render_rule("fence", lambda *a: _fence_renderer(*a[-4:]))


def render_markdown(text: str) -> str:
    return _md.render(text)
