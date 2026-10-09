// Runs the viewer's inline script against a minimal fake DOM and a scripted board server.
// Usage: node viewer_harness.js <index.html> <main|eof|hang>; prints a JSON report.
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.split("<script>")[1].split("</script>")[0];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const created = [];
const revoked = [];
const requests = [];
const storage = new Map();

class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parent = null;
    this.dataset = {};
    this.listeners = {};
    this.textContent = "";
    this.hidden = false;
  }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { return this.children[this.children.length - 1] || null; }
  get nextElementSibling() {
    if (!this.parent) return null;
    const siblings = this.parent.children;
    return siblings[siblings.indexOf(this) + 1] || null;
  }
  get isConnected() {
    let node = this;
    while (node.parent) node = node.parent;
    return node === root;
  }
  append(...nodes) { for (const node of nodes) this.insertBefore(node, null); }
  insertBefore(node, ref) {
    node.remove();
    const index = ref ? this.children.indexOf(ref) : this.children.length;
    this.children.splice(index, 0, node);
    node.parent = this;
    return node;
  }
  remove() {
    if (!this.parent) return;
    this.parent.children.splice(this.parent.children.indexOf(this), 1);
    this.parent = null;
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  focus() {}
  click() {}
}

const root = new El("html");
const body = new El("body");
root.append(body);
const byId = {};
for (const [id, tag] of [["posts", "ol"], ["status", "span"], ["empty", "p"],
                         ["auth", "form"], ["token", "input"]]) {
  byId[id] = new El(tag);
  body.append(byId[id]);
}
byId.auth.hidden = true;
byId.token.value = "";

const encoder = new TextEncoder();
const post = (id, extra = {}) => ({id, board: "general", author: "main_3f9a1c2e",
  text: "post " + id, mentions: [], meme: null, reply_to: null,
  created_at: "2026-10-08T14:03:00Z", attachments: [], ...extra});
const event = (p, eol = "\n") => ["id: " + p.id, "event: post", "data: " + JSON.stringify(p),
                                  "", ""].join(eol);
const image = {id: "att_0123456789ab", name: "plot.png", size: 2048, mime: "image/png",
               kind: "image"};
const initial = [post(1), post(2, {reply_to: 1, mentions: ["main_3f9a1c2e"], meme: "ok",
  attachments: [image, {id: "att_bad", name: "x", size: 1, kind: "image"},
                {id: "att_ffffffffffff", name: "notes.md", size: 12, kind: "file"}]})];

const scenario = process.argv[3] || "main";
const scale = scenario === "main" ? 1 : 20;  // eof/hang compress page timers 20x
if (scenario !== "main") storage.set("dagiBoardToken", "secret");
const history = [];
let statusText = "";
Object.defineProperty(byId.status, "textContent", {
  get: () => statusText,
  set: (value) => { statusText = value; history.push(value); },
});

function firstStream() {
  const block3 = event(post(3));
  const hostile = event(post(214, {text: "<img src=x onerror=alert(1)>"}), "\r\n");
  const chunks = [": ping\n\n", block3.slice(0, 20), block3.slice(20), event(post(2))];
  for (let id = 4; id < 214; id++) chunks.push(event(post(id)));
  const cut = hostile.indexOf("\r\n\r\n") + 1;
  chunks.push(hostile.slice(0, cut), hostile.slice(cut), event(post(213)));
  return new ReadableStream({
    async start(controller) {
      await sleep(150);
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

const hang = (signal) => new Promise((resolve, reject) => {
  signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
});
const pingForever = () => new ReadableStream({
  start(controller) { controller.enqueue(encoder.encode(": ping\n\n")); },
});
const closeAtOnce = () => new ReadableStream({start(controller) { controller.close(); }});

const calls = {};
async function fakeFetch(path, options) {
  const auth = options.headers.Authorization || null;
  requests.push([path, auth]);
  const kind = path.split("?")[0];
  calls[kind] = (calls[kind] || 0) + 1;
  if (auth !== "Bearer secret") return new Response("{}", {status: 401});
  if (scenario === "hang" && calls[kind] === 1) return hang(options.signal);
  if (path === "/posts?limit=50") return new Response(JSON.stringify(initial));
  if (path === "/attachments/" + image.id) {
    return new Response(new Blob([new Uint8Array([137, 80, 78, 71])], {type: "image/png"}));
  }
  if (kind === "/stream") {
    if (scenario === "eof") return new Response(closeAtOnce());
    if (scenario === "hang") return new Response(pingForever());
    return new Response(calls[kind] === 1 ? firstStream() : new ReadableStream({start() {}}));
  }
  return new Response("{}", {status: 404});
}

const context = {
  document: {
    getElementById: (id) => byId[id],
    createElement: (tag) => { const node = new El(tag); created.push(node); return node; },
    body,
  },
  window: {addEventListener() {}},
  navigator: {onLine: true},
  sessionStorage: {getItem: (k) => storage.get(k) || null, setItem: (k, v) => storage.set(k, v)},
  fetch: fakeFetch,
  URL: {createObjectURL: (blob) => URL.createObjectURL(blob),
        revokeObjectURL: (url) => revoked.push(url)},
  setTimeout: (fn, ms) => setTimeout(fn, (ms || 0) / scale),
  Blob, TextDecoder, AbortController, clearTimeout, console,
};

function countdowns() {
  // The first "reconnecting in Ns" of each countdown is the backoff delay chosen.
  const starts = [];
  history.forEach((text, i) => {
    const match = /^reconnecting in (\d+)s$/.exec(text);
    if (match && !/^reconnecting/.test(history[i - 1] || "")) starts.push(Number(match[1]));
  });
  return starts;
}

function snapshot() {
  const ids = byId.posts.children.map((node) => Number(node.dataset.id));
  const top = byId.posts.children[0];
  const text = top && top.children.find((node) => node.tagName === "P");
  const img = created.find((node) => node.tagName === "IMG");
  return {status: statusText, authVisible: !byId.auth.hidden,
          token: storage.get("dagiBoardToken") || null, requests: requests.slice(), ids,
          hostileText: text ? text.textContent : null, imageSrc: img ? img.src || null : null,
          revoked: revoked.slice(), countdowns: countdowns()};
}

(async () => {
  vm.runInNewContext(script, context);
  await sleep(50);
  const first = snapshot();
  if (scenario === "main") {
    byId.token.value = " secret ";
    for (const fn of byId.auth.listeners.submit) fn({preventDefault() {}});
  }
  await sleep(scenario === "eof" ? 1000 : 2000);
  process.stdout.write(JSON.stringify({first, final: snapshot()}));
  process.exit(0);
})().catch((err) => { console.error(err); process.exit(1); });
