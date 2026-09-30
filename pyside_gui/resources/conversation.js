// conversation.js — DOM API called from Python via runJavaScript.
//
// Markdown arrives raw and is rendered here with Lute (Vditor's engine) plus
// Vditor's code, highlight.js and KaTeX renderers. Raw HTML written by the
// model stays literal text: `prepare()` escapes `<` outside code and math.

const STREAM_RENDER_MS = 120;
const HLJS = { enable: true, style: 'tokyo-night-dark', lineNumber: false };
const MATH_OPTIONS = { engine: 'KaTeX', inlineDigit: true, macros: {} };
let _cdnUrl = null;

// Vditor lazy-loads KaTeX / highlight.js from <cdn>/dist/js/...
function _cdn() {
    if (!_cdnUrl) _cdnUrl = new URL('vditor', location.href).href;
    return _cdnUrl;
}

const ICONS = {
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4-4"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.5 2.5 14.5 0 17M12 3.5c-2.5 2.5-2.5 14.5 0 17"/>',
    tool: '<path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>',
    chevron: '<path d="M9 6l6 6-6 6"/>',
};

let _autoScroll = true;
let _lute = null;
const _toolCallStack = [];
let _reasoningStart = 0;

const _observer = new IntersectionObserver(
    (entries) => { _autoScroll = entries[0].isIntersecting; },
    { threshold: 0.1 }
);

document.addEventListener('DOMContentLoaded', () => {
    const sentinel = document.getElementById('scroll-sentinel');
    if (sentinel) _observer.observe(sentinel);
});

// ---- helpers ---------------------------------------------------------------

function _icon(name, cls = 'icon') {
    return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.tool}</svg>`;
}

function _scrollToBottom() {
    if (_autoScroll) {
        const sentinel = document.getElementById('scroll-sentinel');
        if (sentinel) sentinel.scrollIntoView({ block: 'end' });
    }
}

function scrollToBottom() {
    _autoScroll = true;
    _scrollToBottom();
}

function _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Every new block goes in before the sentinel; the welcome screen leaves as
// soon as anything is added.
function _insert(el) {
    const empty = document.getElementById('empty-state');
    if (empty) empty.remove();
    const sentinel = document.getElementById('scroll-sentinel');
    sentinel.parentNode.insertBefore(el, sentinel);
    _scrollToBottom();
    return el;
}

function _el(tag, className, html) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (html !== undefined) el.innerHTML = html;
    return el;
}

// ---- markdown --------------------------------------------------------------

function _getLute() {
    if (_lute) return _lute;
    _lute = Lute.New();
    _lute.SetSanitize(true);
    _lute.SetGFMAutoLink(true);
    _lute.SetFootnotes(true);
    _lute.SetCallout(true);
    _lute.SetIndentCodeBlock(false);
    _lute.SetInlineMathAllowDigitAfterOpenMarker(true);
    _lute.SetAutoSpace(false);
    _lute.SetFixTermTypo(false);
    _lute.SetChineseParagraphBeginningSpace(false);
    _lute.SetToC(false);
    _lute.SetHeadingAnchor(false);
    return _lute;
}

// Inline pass: \( \) and \[ \] become $ and $$; `<` outside code spans, math
// and autolinks becomes &lt; so model-written HTML shows as text.
function _prepareInline(s) {
    let out = '';
    let i = 0;
    while (i < s.length) {
        const c = s[i];
        if (c === '\\' && (s[i + 1] === '(' || s[i + 1] === '[')) {
            const display = s[i + 1] === '[';
            const close = s.indexOf(display ? '\\]' : '\\)', i + 2);
            if (close > i + 2) {
                const inner = s.slice(i + 2, close).trim();
                out += display ? `$$${inner}$$` : `$${inner}$`;
                i = close + 2;
                continue;
            }
        }
        if (c === '\\' && i + 1 < s.length) {
            out += s.slice(i, i + 2);
            i += 2;
            continue;
        }
        if (c === '`') {
            let n = 1;
            while (s[i + n] === '`') n++;
            const ticks = '`'.repeat(n);
            const end = s.indexOf(ticks, i + n);
            if (end >= 0) {
                out += s.slice(i, end + n);
                i = end + n;
            } else {
                out += ticks;
                i += n;
            }
            continue;
        }
        if (c === '$') {
            const delim = s[i + 1] === '$' ? '$$' : '$';
            const start = i + delim.length;
            const end = s.indexOf(delim, start);
            const tight = delim === '$$' || (s[start] !== ' ' && s[end - 1] !== ' ');
            if (end > start && tight) {
                out += s.slice(i, end + delim.length);
                i = end + delim.length;
            } else {
                out += delim;
                i = start;
            }
            continue;
        }
        if (c === '<') {
            const auto = /^<(https?:\/\/[^\s<>]+)>/.exec(s.slice(i));
            if (auto) {
                out += auto[0];
                i += auto[0].length;
                continue;
            }
            out += '&lt;';
            i++;
            continue;
        }
        out += c;
        i++;
    }
    return out;
}

// Returns the prepared text plus whether it ends inside an unclosed fence
// (a code block still being streamed).
function _scanMarkdown(md) {
    const lines = md.replace(/\r\n?/g, '\n').split('\n');
    const out = [];
    let fence = null;           // open ``` / ~~~ fence: {ch, len}
    let math = null;            // open display math: '$$' or '\\]'
    for (const line of lines) {
        const trimmed = line.trim();
        if (fence) {
            out.push(line);
            const m = /^\s*(`{3,}|~{3,})\s*$/.exec(line);
            if (m && m[1][0] === fence.ch && m[1].length >= fence.len) fence = null;
            continue;
        }
        if (math) {
            if (math === '$$' && trimmed === '$$') { out.push(line); math = null; continue; }
            if (math === '\\]' && trimmed.endsWith('\\]')) {
                const body = trimmed.slice(0, -2).trim();
                if (body) out.push(body);
                out.push('$$');
                math = null;
                continue;
            }
            out.push(line);
            continue;
        }
        const open = /^\s*(`{3,}|~{3,})/.exec(line);
        if (open) {
            fence = { ch: open[1][0], len: open[1].length };
            out.push(line);
            continue;
        }
        if (trimmed === '$$') { out.push(line); math = '$$'; continue; }
        if (trimmed.startsWith('\\[') && !trimmed.slice(2).includes('\\]')) {
            out.push('$$');
            const body = trimmed.slice(2).trim();
            if (body) out.push(body);
            math = '\\]';
            continue;
        }
        if (trimmed.startsWith('\\[') && trimmed.endsWith('\\]')) {
            out.push('$$', trimmed.slice(2, -2).trim(), '$$');
            continue;
        }
        out.push(_prepareInline(line));
    }
    if (math === '\\]') out.push('$$');
    return { text: out.join('\n'), openFence: !!fence };
}

function prepareMarkdown(md) {
    return _scanMarkdown(md).text;
}

// `streaming`: the text is still arriving, so a mermaid fence left open at
// the end is shown as a placeholder instead of being drawn half-written.
function renderMarkdownInto(el, md, streaming = false) {
    const { text, openFence } = _scanMarkdown(md || '');
    el.innerHTML = _getLute().Md2HTML(text);
    el.classList.add('vditor-reset', 'md');
    Vditor.codeRender(el);
    Vditor.highlightRender(HLJS, el, _cdn());
    Vditor.mathRender(el, { cdn: _cdn(), math: MATH_OPTIONS });
    renderMermaid(el, streaming && openFence);
}

// ---- mermaid ---------------------------------------------------------------
//
// Mermaid is loaded on first use from the vendored copy and always runs with
// securityLevel "strict": diagram source comes from the model, so `click`
// callbacks and raw HTML labels stay inert. Colours come from the theme
// tokens. Each source is drawn once; the stream bubble re-renders every
// 120 ms and reuses the cached SVG instead of redrawing.

const _mermaidCache = new Map();    // source -> Promise<{svg} | {error}>
let _mermaidLoad = null;
let _mermaidSeq = 0;

function _token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

// Mermaid derives shades from its colours, so translucent tokens are
// flattened onto the chat background first.
function _solid(name) {
    const value = _token(name);
    const m = /^rgba?\(([^)]+)\)$/.exec(value);
    if (!m) return value;
    const [r, g, b, a = 1] = m[1].split(',').map(Number);
    const bg = _token('chat-bg').replace('#', '');
    const mix = (c, i) => Math.round(c * a + parseInt(bg.slice(i, i + 2), 16) * (1 - a));
    return '#' + [mix(r, 0), mix(g, 2), mix(b, 4)].map((c) => c.toString(16).padStart(2, '0')).join('');
}

// Pie slices, git branches and quadrant/xy series cycle through the role
// colours (desaturated onto the chat background so labels stay readable).
const _SERIES = ['accent', 'tool-fg', 'thinking-fg', 'context-fg', 'tokens-fg', 'link', 'success', 'warn'];

function _seriesColours() {
    const out = { pieStrokeColor: _token('chat-bg'), pieOuterStrokeColor: _token('chat-bg'),
                  pieStrokeWidth: '2px', pieOpacity: '0.85', pieTitleTextColor: _solid('fg'),
                  pieSectionTextColor: _token('chat-bg'), pieLegendTextColor: _solid('fg') };
    for (let i = 0; i < 12; i++) {
        const colour = _solid(_SERIES[i % _SERIES.length]);
        out[`pie${i + 1}`] = colour;
        out[`git${i}`] = colour;
        out[`cScale${i}`] = colour;
    }
    return out;
}

function _mermaidConfig() {
    const fg = _solid('fg');
    return {
        startOnLoad: false,
        securityLevel: 'strict',
        suppressErrorRendering: true,
        theme: 'base',
        fontFamily: _token('font-ui'),
        themeVariables: Object.assign(_seriesColours(), {
            darkMode: true,
            fontFamily: _token('font-ui'),
            fontSize: '13px',
            background: _token('chat-bg'),
            primaryColor: _token('composer-bg'),
            primaryTextColor: fg,
            primaryBorderColor: _token('accent'),
            secondaryColor: _token('active-bg'),
            tertiaryColor: _token('hover-bg'),
            mainBkg: _token('composer-bg'),
            nodeBorder: _token('accent'),
            textColor: fg,
            titleColor: fg,
            lineColor: _solid('fg-secondary'),
            clusterBkg: _token('app-bg'),
            clusterBorder: _token('composer-border'),
            edgeLabelBackground: _token('chat-bg'),
            noteBkgColor: _token('menu-bg'),
            noteTextColor: fg,
            noteBorderColor: _token('composer-border'),
        }),
    };
}

function _loadMermaid() {
    if (!_mermaidLoad) {
        _mermaidLoad = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = `${_cdn()}/dist/js/mermaid/mermaid.min.js`;
            script.onload = () => {
                mermaid.initialize(_mermaidConfig());
                resolve();
            };
            script.onerror = () => {
                _mermaidLoad = null;
                reject(new Error('the diagram renderer failed to load'));
            };
            document.head.appendChild(script);
        });
    }
    return _mermaidLoad;
}

function _drawMermaid(source) {
    if (!_mermaidCache.has(source)) {
        const id = `mermaid-${++_mermaidSeq}`;
        const job = _loadMermaid()
            .then(() => mermaid.render(id, source))
            .then(({ svg }) => ({ svg }))
            .catch((err) => {
                for (const stray of [id, `d${id}`]) {
                    const el = document.getElementById(stray);
                    if (el) el.remove();
                }
                // Parse errors are "Parse error on line N:", the offending line,
                // a caret line, then "Expecting …": keep the first and last.
                const lines = String((err && err.message) || err).trim().split('\n');
                const message = lines.length > 1 ? `${lines[0]} ${lines[lines.length - 1]}` : lines[0];
                return { error: message || 'invalid diagram' };
            });
        _mermaidCache.set(source, job);
    }
    return _mermaidCache.get(source);
}

function _copyText(text) {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
}

function _mermaidCard(source) {
    const card = _el('div', 'mermaid-card pending',
        '<div class="mermaid-toolbar">' +
        '<button type="button" class="mermaid-btn" data-act="toggle">Code</button>' +
        '<button type="button" class="mermaid-btn" data-act="copy">Copy</button>' +
        '</div>' +
        '<div class="mermaid-diagram"><div class="mermaid-pending">Drawing diagram…</div></div>' +
        '<pre class="mermaid-source" hidden><code class="mermaid-code"></code></pre>');
    card.querySelector('.mermaid-source code').textContent = source;
    card.querySelector('[data-act="toggle"]').addEventListener('click', (event) => {
        const showCode = card.classList.toggle('show-code');
        card.querySelector('.mermaid-source').hidden = !showCode && !card.classList.contains('failed');
        card.querySelector('.mermaid-diagram').hidden = showCode;
        event.currentTarget.textContent = showCode ? 'Diagram' : 'Code';
    });
    card.querySelector('[data-act="copy"]').addEventListener('click', (event) => {
        const button = event.currentTarget;
        _copyText(source);
        button.textContent = 'Copied';
        setTimeout(() => { button.textContent = 'Copy'; }, 1200);
    });
    return card;
}

function _fillMermaidCard(card, result) {
    card.classList.remove('pending');
    const diagram = card.querySelector('.mermaid-diagram');
    if (result.error) {
        card.classList.add('failed');
        card.querySelector('[data-act="toggle"]').hidden = true;
        card.querySelector('.mermaid-source').hidden = false;
        diagram.innerHTML = '<div class="mermaid-error"></div>';
        diagram.firstChild.textContent = `Couldn't draw this diagram: ${result.error}`;
        card.appendChild(diagram);      // error line goes under the source
        return;
    }
    diagram.innerHTML = result.svg;
    // Natural size: wide diagrams scroll sideways rather than shrink.
    const svg = diagram.querySelector('svg');
    if (svg && svg.style.maxWidth) {
        svg.setAttribute('width', svg.style.maxWidth);
        svg.style.maxWidth = '';
    }
}

// Swaps every mermaid fence Lute produced (`.language-mermaid`) for a card.
// `lastPending`: the final fence is still streaming; show a placeholder.
function renderMermaid(el, lastPending = false) {
    let tail = el;
    while (tail.lastElementChild) tail = tail.lastElementChild;
    const blocks = Array.from(el.querySelectorAll('.language-mermaid'))
        .filter((block) => !block.closest('.mermaid-card'));
    blocks.forEach((block) => {
        const host = block.parentElement && block.parentElement.tagName === 'PRE'
            ? block.parentElement : block;
        const source = block.textContent.trim();
        const open = lastPending && host.contains(tail);   // the fence still streaming
        const card = _mermaidCard(source);
        host.replaceWith(card);
        if (!source || open) return;
        _drawMermaid(source).then((result) => {
            if (!card.isConnected) return;
            _fillMermaidCard(card, result);
            _scrollToBottom();
        });
    });
}

// ---- welcome ---------------------------------------------------------------

function showWelcome(title, subtitle, imageUrl) {
    let empty = document.getElementById('empty-state');
    if (!empty) {
        empty = _el('div', 'empty-state');
        empty.id = 'empty-state';
        const conv = document.getElementById('conversation');
        conv.insertBefore(empty, conv.firstChild);
    }
    const image = imageUrl
        ? `<img class="empty-pet" src="${_escapeHtml(imageUrl)}" alt="">`
        : '';
    empty.innerHTML = image +
        `<div class="empty-title">${_escapeHtml(title)}</div>` +
        `<div class="empty-subtitle">${_escapeHtml(subtitle)}</div>`;
}

// ---- messages --------------------------------------------------------------

function appendMessage(role, text) {
    if (role !== 'user') return appendMarkdown(text);
    _insert(_el('div', 'message user-message',
        `<div class="message-body">${_escapeHtml(text)}</div>`));
}

function appendUserMessageWithImages(text, imagePaths) {
    const div = _el('div', 'message user-message');
    let html = '';
    if (imagePaths && imagePaths.length > 0) {
        html += '<div class="image-gallery">';
        for (const path of imagePaths) {
            html += `<img class="sent-image-thumb" src="${_escapeHtml(path)}" alt="Sent image" />`;
        }
        html += '</div>';
    }
    if (text) html += `<div class="message-body">${_escapeHtml(text)}</div>`;
    div.innerHTML = html;
    _insert(div);
}

function appendMarkdown(md) {
    const div = _el('div', 'message assistant-message');
    const body = _el('div', 'message-body');
    div.appendChild(body);
    renderMarkdownInto(body, md);
    _insert(div);
}

function appendInfo(text) {
    _insert(_el('div', 'info-message')).textContent = text;
}

function appendError(text) {
    _insert(_el('div', 'error-message')).textContent = text;
}

// ---- tool calls ------------------------------------------------------------

// JSON arguments become one labelled field per key: strings keep their real
// line breaks, other values are pretty-printed. Anything else stays raw.
function _renderArgs(args) {
    let data = null;
    try { data = JSON.parse(args); } catch (e) { data = null; }
    if (!data || typeof data !== 'object' || Array.isArray(data) || !Object.keys(data).length) {
        const raw = _el('pre', 'tool-args');
        raw.textContent = data && typeof data === 'object' ? JSON.stringify(data, null, 2) : args;
        return raw;
    }
    const box = _el('div', 'tool-args');
    for (const [key, value] of Object.entries(data)) {
        const field = _el('div', 'tool-arg');
        const name = _el('div', 'tool-arg-key');
        name.textContent = key;
        const val = _el('pre', 'tool-arg-value');
        val.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
        field.appendChild(name);
        field.appendChild(val);
        box.appendChild(field);
    }
    return box;
}

function _toggle(row) {
    const open = row.classList.toggle('open');
    row.querySelector('.tool-detail').hidden = !open;
}

function appendToolCall(label, kind, args, verbose) {
    const row = _el('div', 'tool-call running');
    row.id = `tool-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const head = _el('div', 'tool-head',
        _icon('chevron', 'chevron') + _icon(kind) +
        `<span class="tool-label"></span><span class="tool-status"></span>`);
    head.querySelector('.tool-label').textContent = label;
    head.addEventListener('click', () => _toggle(row));
    const detail = _el('div', 'tool-detail');
    detail.hidden = true;
    detail.appendChild(_renderArgs(args));
    row.appendChild(head);
    row.appendChild(detail);
    _insert(row);
    if (verbose) _toggle(row);
    _toolCallStack.push(row.id);
    return row.id;
}

function updateToolResult(result, failed) {
    const callId = _toolCallStack.pop();
    const row = callId && document.getElementById(callId);
    if (!row) return;
    row.classList.remove('running');
    row.classList.add(failed ? 'failed' : 'done');
    const lines = result ? result.split('\n').length : 0;
    row.querySelector('.tool-status').textContent =
        (failed ? '✕' : '✓') + (lines > 1 ? ` ${lines} lines` : '');
    const out = _el('pre', 'tool-result');
    out.textContent = result;
    row.querySelector('.tool-detail').appendChild(out);
    _scrollToBottom();
}

// ---- reasoning -------------------------------------------------------------

function _thought(summary) {
    const div = _el('details', 'message reasoning-message');
    div.innerHTML =
        `<summary>${_icon('chevron', 'chevron')}<span class="thought-label">${summary}</span></summary>` +
        '<div class="message-body"></div>';
    return div;
}

function appendReasoning(md) {
    const div = _thought('Thought');
    renderMarkdownInto(div.querySelector('.message-body'), md);
    _insert(div);
}

function createStreamBubble() {
    const existing = document.getElementById('streaming-bubble');
    if (existing) existing.remove();
    _reasoningStart = 0;
    const div = _el('div', 'message assistant-message streaming',
        '<div class="message-body text"></div>');
    div.id = 'streaming-bubble';
    div._md = '';
    _insert(div);
}

function updateReasoningPreview(text) {
    const bubble = document.getElementById('streaming-bubble');
    if (!bubble) return;
    let reasoning = document.getElementById('streaming-reasoning');
    if (!reasoning) {
        if (!text.trim()) return;
        _reasoningStart = performance.now();
        reasoning = _el('div', 'message reasoning-message reasoning-streaming',
            `<div class="thought-live">${_icon('chevron', 'chevron')}<span>Thinking…</span></div>` +
            '<div class="message-body reasoning-preview"></div>');
        reasoning.id = 'streaming-reasoning';
        bubble.parentNode.insertBefore(reasoning, bubble);
    }
    const body = reasoning.querySelector('.reasoning-preview');
    body.textContent = text.trimEnd();
    // Cap visible wrapped lines, not source lines, and follow the newest text.
    body.scrollTop = body.scrollHeight;
    _scrollToBottom();
}

function finalizeReasoning(md) {
    const live = document.getElementById('streaming-reasoning');
    if (!live) return;
    const seconds = _reasoningStart ? Math.max(1, Math.round((performance.now() - _reasoningStart) / 1000)) : 0;
    const done = _thought(seconds ? `Thought for ${seconds}s` : 'Thought');
    done.id = 'streaming-reasoning';
    renderMarkdownInto(done.querySelector('.message-body'), md);
    live.replaceWith(done);
    _scrollToBottom();
}

function _renderStream(bubble) {
    bubble._timer = 0;
    renderMarkdownInto(bubble.querySelector('.message-body'), bubble._md, true);
    _scrollToBottom();
}

function updateStreamBubble(kind, chunk) {
    const bubble = document.getElementById('streaming-bubble');
    if (!bubble || kind !== 'text') return;
    bubble._md += chunk;
    if (!bubble._timer) bubble._timer = setTimeout(() => _renderStream(bubble), STREAM_RENDER_MS);
}

function finalizeStream(md) {
    const reasoning = document.getElementById('streaming-reasoning');
    if (reasoning) reasoning.id = '';
    const bubble = document.getElementById('streaming-bubble');
    if (!bubble) return;
    clearTimeout(bubble._timer);
    bubble._timer = 0;
    bubble.id = '';
    if (!md.trim()) {
        bubble.remove();
        _scrollToBottom();
        return;
    }
    bubble.classList.remove('streaming');
    renderMarkdownInto(bubble.querySelector('.message-body'), md);
    _scrollToBottom();
}

// Esc: freeze the live answer as it stands. Late deltas then find no
// bubble and are dropped; the eventual finalizeStream is a no-op.
function interruptStream() {
    const bubble = document.getElementById('streaming-bubble');
    if (bubble) finalizeStream(bubble._md || '');
}

function clearConversation() {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    while (conv.firstChild && conv.firstChild !== sentinel) {
        conv.removeChild(conv.firstChild);
    }
    _toolCallStack.length = 0;
}

// ---- question, emote, subagent --------------------------------------------

function appendQuestion(questionMd, options, timeout) {
    const div = _el('div', 'question-panel', '<div class="question-header">Question</div>');
    const body = _el('div', 'question-body');
    renderMarkdownInto(body, questionMd);
    div.appendChild(body);
    if (options.length > 0) {
        const list = _el('ol', 'question-options');
        options.forEach((opt) => {
            const item = _el('li');
            const rec = opt.recommended ? ' <span class="recommended">recommended</span>' : '';
            item.innerHTML = `<span class="option-label">${_escapeHtml(opt.label)}</span>${rec}` +
                (opt.description ? `<div class="option-description">${_escapeHtml(opt.description)}</div>` : '');
            list.appendChild(item);
        });
        div.appendChild(list);
    }
    if (timeout) {
        div.appendChild(_el('div', 'question-timeout',
            `Auto-selects in ${Math.floor(timeout)}s — type your answer below.`));
    }
    _insert(div);
}

function appendEmoteCard(name, fileUrl, text, timestamp) {
    const div = _el('div', 'emote-card');
    const img = document.createElement('img');
    img.className = 'emote-img';
    img.src = fileUrl;
    img.alt = name;
    img.onerror = () => { img.replaceWith(_el('div', 'emote-missing', _escapeHtml(`[${name}]`))); };
    const meta = _el('div', 'emote-meta',
        `<div class="emote-text">${_escapeHtml(text)}</div>` +
        `<div class="emote-time">${_escapeHtml(timestamp)}</div>`);
    div.appendChild(img);
    div.appendChild(meta);
    _insert(div);
}

function _subagentBlock(subagentType) {
    let block = document.getElementById(`subagent-${subagentType}`);
    if (!block) {
        block = _el('div', 'subagent-block',
            `<div class="subagent-header">${_icon('tool')}<span>Subagent · ${_escapeHtml(subagentType)}</span></div>`);
        block.id = `subagent-${subagentType}`;
        _insert(block);
    }
    return block;
}

function appendSubagentEvent(subagentType, eventJson) {
    const evt = JSON.parse(eventJson);
    const t = evt.type || '';
    const block = _subagentBlock(subagentType);
    if (t === 'start') return;
    const line = _el('div', 'subagent-line');
    if (t === 'tool_call') {
        line.textContent = `${evt.name || '?'} ${(evt.args || '').replace(/\s+/g, ' ').slice(0, 80)}`;
    } else if (t === 'tool_result') {
        line.textContent = `✓ ${evt.name || '?'} (${evt.chars || 0} chars)`;
    } else if (t === 'message') {
        line.classList.add('subagent-message');
        line.textContent = evt.content || '';
    } else if (t === 'error') {
        line.classList.add('subagent-error');
        line.textContent = `error: ${evt.message || ''}`;
    } else if (t === 'done') {
        block.classList.add('done');
        block.querySelector('.subagent-header span').textContent = `Subagent · ${subagentType} · done`;
        block.id = '';
        _scrollToBottom();
        return;
    } else if (t === 'status') {
        line.textContent = evt.text || '';
    } else {
        return;
    }
    block.appendChild(line);
    _scrollToBottom();
}
