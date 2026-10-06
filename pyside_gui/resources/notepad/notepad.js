/* Pet notepad: Vditor (instant-rendering mode) bridged to Python over QWebChannel.
 *
 * Python -> JS:  npSetMarkdown(text), npGetMarkdown() -> string, npFocus()
 * JS -> Python:  bridge.onReady(), bridge.contentChanged(md),
 *                bridge.saveRequested(), bridge.openLink(url)
 */
(function () {
    "use strict";

    const CDN = new URL("../vditor", location.href).href.replace(/\/$/, "");
    let bridge = null;
    let vditor = null;
    let suppressInput = false;

    // Vditor's preview configures mermaid with securityLevel "loose" (click
    // callbacks, raw HTML labels). Notes can hold model-written text, so every
    // configuration is pinned to "strict" as soon as the library loads.
    let mermaidLib;
    Object.defineProperty(window, "mermaid", {
        configurable: true,
        get: function () { return mermaidLib; },
        set: function (lib) {
            const initialize = lib.initialize.bind(lib);
            lib.initialize = function (config) {
                initialize(Object.assign({}, config, { securityLevel: "strict" }));
            };
            mermaidLib = lib;
        },
    });

    function linkUnder(target) {
        const anchor = target.closest("a[href]");
        if (anchor) return anchor.getAttribute("href");
        const node = target.closest('.vditor-ir__node[data-type="a"]');
        if (!node) return null;
        const marker = node.querySelector(".vditor-ir__marker--link");
        return marker ? marker.textContent.trim() : null;
    }

    // Theme names come from pyside_gui/theme.py tokens (--color-scheme etc.).
    function token(name) {
        return getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();
    }

    function initEditor() {
        const scheme = token("color-scheme") === "light" ? "light" : "dark";
        vditor = new Vditor("editor", {
            cdn: CDN,
            mode: "ir",
            lang: "en_US",
            icon: "ant",
            theme: scheme === "light" ? "classic" : "dark",
            height: "100%",
            placeholder: "Notes… markdown and $math$",
            toolbar: [],
            toolbarConfig: { hide: true },
            cache: { enable: false },
            counter: { enable: false },
            outline: { enable: false },
            link: { isOpen: false },
            preview: {
                theme: { current: scheme, path: CDN + "/dist/css/content-theme" },
                math: { engine: "KaTeX", inlineDigit: false },
                hljs: { enable: true, style: token("hljs-style"), lineNumber: false },
            },
            input: function (md) {
                if (!suppressInput) bridge.contentChanged(md);
            },
            after: function () {
                bridge.onReady();
            },
        });
    }

    window.npSetMarkdown = function (text) {
        suppressInput = true;
        try {
            vditor.setValue(text, true);
        } finally {
            suppressInput = false;
        }
    };

    window.npGetMarkdown = function () {
        return vditor ? vditor.getValue() : null;
    };

    window.npFocus = function () {
        if (vditor) vditor.focus();
    };

    function inPlainParagraph() {
        const sel = window.getSelection();
        if (!sel || !sel.anchorNode) return false;
        const node = sel.anchorNode.nodeType === Node.ELEMENT_NODE
            ? sel.anchorNode : sel.anchorNode.parentElement;
        if (!node || !node.closest(".vditor-ir")) return false;
        const block = node.closest("[data-block]");
        return !!block && block.tagName === "P" && !node.closest("li, table, pre:not(.vditor-reset)");
    }

    // Notepad-style line breaks: in plain paragraphs Enter inserts a single line
    // break and Shift+Enter starts a new paragraph (Vditor's defaults, swapped).
    // Lists, headings, code and math blocks keep Vditor's own Enter handling.
    document.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" || !event.isTrusted || event.isComposing
            || event.ctrlKey || event.altKey || event.metaKey || !inPlainParagraph()) {
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        // execCommand fires a native input event, which Vditor re-renders from.
        document.execCommand(event.shiftKey ? "insertParagraph" : "insertLineBreak");
    }, true);

    document.addEventListener("keydown", function (event) {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
            event.preventDefault();
            event.stopPropagation();
            if (bridge) bridge.saveRequested();
        }
    }, true);

    // Ctrl+click follows a link in the system browser; plain clicks keep editing.
    document.addEventListener("click", function (event) {
        if (!(event.ctrlKey || event.metaKey) || !bridge) return;
        const href = linkUnder(event.target);
        if (href) {
            event.preventDefault();
            bridge.openLink(href);
        }
    }, true);

    new QWebChannel(qt.webChannelTransport, function (channel) {
        bridge = channel.objects.notepad;
        initEditor();
    });
})();
