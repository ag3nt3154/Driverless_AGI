/* Pet notepad: Vditor (instant-rendering mode) bridged to Python over QWebChannel.
 *
 * Python -> JS:  npSetMarkdown(text), npGetMarkdown() -> string, npFocus()
 * JS -> Python:  bridge.onReady(), bridge.contentChanged(md),
 *                bridge.saveRequested(), bridge.openLink(url)
 */
(function () {
    "use strict";

    const CDN = new URL("vditor", location.href).href.replace(/\/$/, "");
    let bridge = null;
    let vditor = null;
    let suppressInput = false;

    function linkUnder(target) {
        const anchor = target.closest("a[href]");
        if (anchor) return anchor.getAttribute("href");
        const node = target.closest('.vditor-ir__node[data-type="a"]');
        if (!node) return null;
        const marker = node.querySelector(".vditor-ir__marker--link");
        return marker ? marker.textContent.trim() : null;
    }

    function initEditor() {
        vditor = new Vditor("editor", {
            cdn: CDN,
            mode: "ir",
            lang: "en_US",
            icon: "ant",
            theme: "dark",
            height: "100%",
            placeholder: "Notes… markdown and $math$",
            toolbar: [],
            toolbarConfig: { hide: true },
            cache: { enable: false },
            counter: { enable: false },
            outline: { enable: false },
            link: { isOpen: false },
            preview: {
                theme: { current: "dark", path: CDN + "/dist/css/content-theme" },
                math: { engine: "KaTeX", inlineDigit: false },
                hljs: { enable: true, style: "tokyo-night-dark", lineNumber: false },
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
