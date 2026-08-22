// conversation.js — DOM manipulation API called from Python via runJavaScript

let _autoScroll = true;
const _toolCallStack = [];

const _observer = new IntersectionObserver(
    (entries) => { _autoScroll = entries[0].isIntersecting; },
    { threshold: 0.1 }
);

document.addEventListener('DOMContentLoaded', () => {
    const sentinel = document.getElementById('scroll-sentinel');
    if (sentinel) _observer.observe(sentinel);
});

function _scrollToBottom() {
    if (_autoScroll) {
        const sentinel = document.getElementById('scroll-sentinel');
        if (sentinel) sentinel.scrollIntoView({ behavior: 'smooth' });
    }
}

function _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function appendMessage(role, text) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const div = document.createElement('div');
    const headerText = role === 'user' ? 'You' : 'Dagi';
    div.className = `message ${role}-message`;
    div.innerHTML =
        `<div class="message-header">${headerText}</div>` +
        `<div class="message-body">${_escapeHtml(text)}</div>`;
    conv.insertBefore(div, sentinel);
    _scrollToBottom();
}

function appendMarkdown(html) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const div = document.createElement('div');
    div.className = 'message assistant-message';
    div.innerHTML =
        '<div class="message-header">Dagi</div>' +
        `<div class="message-body rendered-markdown">${html}</div>`;
    conv.insertBefore(div, sentinel);
    _scrollToBottom();
}

function appendToolCall(name, args, verbose) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const div = document.createElement('div');
    const callId = `tool-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    div.className = 'message tool-call';
    div.id = callId;
    const openAttr = verbose ? ' open' : '';
    const displayArgs = verbose ? args : (
        args.length > 120 ? args.replace(/\n/g, ' ').slice(0, 120) + '...' : args.replace(/\n/g, ' ')
    );
    div.innerHTML =
        `<details${openAttr}>` +
        `<summary>▶ ${_escapeHtml(name)}</summary>` +
        `<div class="tool-args">${_escapeHtml(displayArgs)}</div>` +
        `<div class="tool-result"></div>` +
        `</details>`;
    conv.insertBefore(div, sentinel);
    _toolCallStack.push(callId);
    _scrollToBottom();
    return callId;
}

function updateToolResult(name, result, verbose) {
    const callId = _toolCallStack.pop();
    if (!callId) return;
    const div = document.getElementById(callId);
    if (!div) return;
    const resultDiv = div.querySelector('.tool-result');
    if (verbose) {
        resultDiv.textContent = result;
    } else {
        resultDiv.innerHTML =
            `<span class="tool-result-summary">✓ ${result.length} chars</span>`;
    }
    _scrollToBottom();
}

function appendReasoning(text) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const div = document.createElement('div');
    div.className = 'message reasoning-message';
    div.innerHTML =
        '<div class="message-header">🧠 Thinking</div>' +
        `<div class="message-body">${_escapeHtml(text)}</div>`;
    conv.insertBefore(div, sentinel);
    _scrollToBottom();
}

function appendInfo(text) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const div = document.createElement('div');
    div.className = 'info-message';
    div.textContent = text;
    conv.insertBefore(div, sentinel);
    _scrollToBottom();
}

function appendError(text) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const div = document.createElement('div');
    div.className = 'error-message';
    div.textContent = 'Error: ' + text;
    conv.insertBefore(div, sentinel);
    _scrollToBottom();
}

function createStreamBubble() {
    const existing = document.getElementById('streaming-bubble');
    if (existing) existing.remove();
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const div = document.createElement('div');
    div.id = 'streaming-bubble';
    div.className = 'message assistant-message streaming';
    div.innerHTML =
        '<div class="message-header">Dagi</div>' +
        '<div class="reasoning"></div>' +
        '<div class="text"></div>';
    conv.insertBefore(div, sentinel);
    _scrollToBottom();
}

function updateStreamBubble(kind, chunk) {
    const bubble = document.getElementById('streaming-bubble');
    if (!bubble) return;
    const target = bubble.querySelector(`.${kind}`);
    if (!target) return;
    target.textContent += chunk;
    _scrollToBottom();
}

function finalizeStream(html) {
    const bubble = document.getElementById('streaming-bubble');
    if (!bubble) return;
    bubble.classList.remove('streaming');
    bubble.id = '';
    const reasoningDiv = bubble.querySelector('.reasoning');
    const reasoningText = reasoningDiv ? reasoningDiv.textContent.trim() : '';
    if (reasoningText) {
        const rDiv = document.createElement('div');
        rDiv.className = 'message reasoning-message';
        rDiv.innerHTML =
            '<div class="message-header">🧠 Thinking</div>' +
            `<div class="message-body">${_escapeHtml(reasoningText)}</div>`;
        bubble.parentNode.insertBefore(rDiv, bubble);
    }
    bubble.innerHTML =
        '<div class="message-header">Dagi</div>' +
        `<div class="message-body rendered-markdown">${html}</div>`;
}

function clearConversation() {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    while (conv.firstChild && conv.firstChild !== sentinel) {
        conv.removeChild(conv.firstChild);
    }
    _toolCallStack.length = 0;
}

function appendQuestion(question, optionsJson, timeout) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const options = JSON.parse(optionsJson);
    const div = document.createElement('div');
    div.className = 'question-panel';
    let html = `<div class="question-header">Question from Dagi</div>`;
    html += `<p>${_escapeHtml(question)}</p>`;
    if (options.length > 0) {
        html += '<table>';
        options.forEach((opt, i) => {
            const rec = opt.recommended
                ? ' <span class="recommended">(recommended)</span>' : '';
            html += `<tr><td class="option-num">${i + 1}</td>` +
                `<td>${_escapeHtml(opt.label)}${rec}</td>` +
                `<td>${_escapeHtml(opt.description || '')}</td></tr>`;
        });
        html += '</table>';
    }
    if (timeout) {
        html += `<p style="color: var(--text-dim);">` +
            `Auto-selects in ${Math.floor(timeout)}s — type your answer:</p>`;
    }
    div.innerHTML = html;
    conv.insertBefore(div, sentinel);
    _scrollToBottom();
}

function appendSubagentEvent(subagentType, eventJson) {
    const conv = document.getElementById('conversation');
    const sentinel = document.getElementById('scroll-sentinel');
    const evt = JSON.parse(eventJson);
    const t = evt.type || '';
    const div = document.createElement('div');

    if (t === 'start') {
        div.className = 'subagent-block';
        div.id = `subagent-${subagentType}`;
        div.innerHTML =
            `<div class="subagent-header">┌─ subagent: ${_escapeHtml(subagentType)}</div>`;
        conv.insertBefore(div, sentinel);
    } else {
        let block = document.getElementById(`subagent-${subagentType}`);
        if (!block) {
            block = document.createElement('div');
            block.className = 'subagent-block';
            block.id = `subagent-${subagentType}`;
            conv.insertBefore(block, sentinel);
        }
        const line = document.createElement('div');
        if (t === 'tool_call') {
            line.className = 'subagent-tool';
            line.textContent =
                `  ▶ ${evt.name || '?'} ${(evt.args || '').slice(0, 80)}`;
        } else if (t === 'tool_result') {
            line.className = 'subagent-tool';
            line.textContent =
                `  ✓ ${evt.name || '?'} (${evt.chars || 0} chars)`;
        } else if (t === 'message') {
            line.textContent = `  ${evt.content || ''}`;
        } else if (t === 'error') {
            line.className = 'subagent-error';
            line.textContent = `  error: ${evt.message || ''}`;
        } else if (t === 'done') {
            line.className = 'subagent-footer';
            line.textContent =
                `└─ subagent: ${_escapeHtml(subagentType)} done`;
            block.id = '';
        } else if (t === 'status') {
            line.className = 'subagent-tool';
            line.textContent = `  ${evt.text || ''}`;
        }
        block.appendChild(line);
    }
    _scrollToBottom();
}
