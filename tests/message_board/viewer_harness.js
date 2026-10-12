// Runs the viewer's inline script against a minimal fake DOM and a scripted board server.
// Usage: node viewer_harness.js <index.html> <main|eof|hang|outage|attach|compose>; prints JSON.
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.split("<script>")[1].split("</script>")[0];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const created = [];
const revoked = [];
const requests = [];
const requestDetails = [];
const storage = new Map();
const uploaded = [];
const deterministicRandom = [];
let memberPosts = 0;
const intervals = [];  // page setInterval callbacks; scenarios fire them explicitly

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
  replaceChildren(...nodes) { for (const child of this.children.slice()) child.remove(); this.append(...nodes); }
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
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  removeAttribute(name) { delete this[name]; }
  querySelector(selector) {
    const classes = selector.split(",").map((part) => part.trim().split(".").pop());
    return this.children.find((node) => classes.some(
      (cls) => String(node.className || "").split(" ").includes(cls))) || null;
  }
  fire(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
}

const root = new El("html");
const body = new El("body");
root.append(body);
const byId = {};
for (const [id, tag] of [["posts", "ol"], ["status", "span"], ["empty", "p"],
                         ["auth", "form"], ["token", "input"], ["lightbox", "div"],
                         ["lightbox-img", "img"], ["lightbox-name", "span"],
                         ["lightbox-save", "button"], ["lightbox-close", "button"],
                         ["identity", "div"], ["identity-form", "form"], ["identity-name", "input"],
                         ["identity-error", "span"], ["identity-cancel", "button"],
                         ["composer", "form"], ["compose-text", "textarea"], ["counter", "span"],
                         ["send", "button"], ["composer-error", "p"], ["file-input", "input"],
                         ["file-chips", "div"], ["reply-label", "div"], ["mentions", "div"],
                         ["attach", "button"]]) {
  byId[id] = new El(tag);
  body.append(byId[id]);
}
byId.auth.hidden = true;
byId["identity-form"].hidden = true;
byId.mentions.hidden = true;
byId["reply-label"].hidden = true;
byId.lightbox.hidden = true;
const liveHistory = [];
let live;
Object.defineProperty(body.dataset, "live", {
  get: () => live,
  set: (value) => { if (value !== live) liveHistory.push(value); live = value; },
  enumerable: true,
});
const docListeners = {};
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
const notes = "# notes\n<b>not html</b>";
const binary = {id: "att_eeeeeeeeeeee", name: "blob.bin", size: 3, kind: "file"};
const big = {id: "att_dddddddddddd", name: "big.log", size: 300 * 1024, kind: "file"};

const scenario = process.argv[3] || "main";
if (scenario === "attach") initial[1].attachments.push(binary, big);
const scale = scenario === "main" ? 1 : 20;  // eof/hang compress page timers 20x
if (scenario !== "main") storage.set("dagiBoardToken", "secret");
if (["compose", "collision", "compose-first-send", "compose-outage"].includes(scenario)) {
  deterministicRandom.push(...(scenario === "collision"
    ? [[170, 170, 170, 170], [187, 187, 187, 187]] : [[18, 52, 86, 120]]));
}
const outage = (n) => n >= 2 && n <= 3;  // stream calls 2 and 3 find the server down
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
class FakeFormData {
  constructor() { this.fields = []; }
  append(name, value) { this.fields.push([name, value && value.name ? value.name : value]); }
}
const pingForever = () => new ReadableStream({
  start(controller) { controller.enqueue(encoder.encode(": ping\n\n")); },
});
const closeAtOnce = () => new ReadableStream({start(controller) { controller.close(); }});

const calls = {};
async function fakeFetch(path, options) {
  const auth = options.headers.Authorization || null;
  requests.push([path, auth]);
  let parsedBody = options.body;
  if (typeof parsedBody === "string") { try { parsedBody = JSON.parse(parsedBody); } catch (err) {} }
  const details = {path, method: options.method || "GET", body: parsedBody,
                   memberKey: options.headers["X-Dagi-Member-Key"] || null};
  requestDetails.push(details);
  const kind = path.split("?")[0];
  calls[kind] = (calls[kind] || 0) + 1;
  if (auth !== "Bearer secret") return new Response(JSON.stringify({error: "token required", code: "UNAUTHORIZED"}), {status: 401});
  if (scenario === "compose-outage" && kind === "/stream") throw new TypeError("offline");
  if (scenario === "members-race") {
    if (path === "/posts?limit=50") return new Response("[]");
    if (kind === "/stream") return new Response(new ReadableStream({async start(controller) {
      await sleep(5); controller.enqueue(encoder.encode(event(post(1, {author: "late_12345678"}))));
    }}));
    if (path === "/members") {
      if (calls[kind] === 1) { await sleep(40); return new Response("[]"); }
      return new Response(JSON.stringify([{handle: "late_12345678", kind: "agent"}]));
    }
  }
  if (["compose", "collision", "compose-first-send", "compose-outage"].includes(scenario)) {
    if (path === "/posts?limit=50") return new Response(JSON.stringify([post(7)]));
    if (kind === "/stream") return new Response(new ReadableStream({start() {}}));
    if (path === "/members" && (options.method || "GET") === "GET") {
      return new Response(JSON.stringify([{handle: "main_3f9a1c2e", kind: "agent", online: true},
        {handle: "main-old_00000000", kind: "agent", online: false}]));
    }
    if (path === "/members" && options.method === "POST") {
      memberPosts += 1;
      if (scenario === "collision" && memberPosts === 1) {
        return new Response(JSON.stringify({error: "handle already exists", code: "HANDLE_TAKEN"}), {status: 409});
      }
      details.body && (details.bodyAccepted = true);
      return new Response(JSON.stringify(details.body), {status: 201});
    }
    if (path === "/attachments" && options.method === "POST") {
      await sleep(40);
      const id = "att_" + String(uploaded.length + 1).padStart(12, "0");
      const record = {id, fields: parsedBody && parsedBody.fields || []}; uploaded.push(record);
      details.body = record.fields;
      return new Response(JSON.stringify({id}), {status: 201});
    }
    if (path === "/posts" && options.method === "POST") return new Response(JSON.stringify(parsedBody), {status: 201});
  }
  if (path === "/members") return new Response(JSON.stringify([{handle: "main_3f9a1c2e", kind: "agent"}]));
  if (scenario === "hang" && calls[kind] === 1) return hang(options.signal);
  if (path === "/posts?limit=50") return new Response(JSON.stringify(initial));
  if (path === "/attachments/" + image.id) {
    return new Response(new Blob([new Uint8Array([137, 80, 78, 71])], {type: "image/png"}));
  }
  if (path === "/attachments/att_ffffffffffff") return new Response(new Blob([notes]));
  if (path === "/attachments/" + binary.id) {
    return new Response(new Blob([new Uint8Array([0, 1, 2])]));
  }
  if (kind === "/stream" && scenario === "outage") {
    if (calls[kind] === 1) {
      return new Response(new ReadableStream({async start(controller) {
        controller.enqueue(encoder.encode(event(post(3))));
        await sleep(30);
        controller.error(new TypeError("network error"));
      }}));
    }
    if (outage(calls[kind])) throw new TypeError("Failed to fetch");
    return new Response(calls[kind] === 4
      ? new ReadableStream({start(controller) {
        controller.enqueue(encoder.encode(event(post(4)) + event(post(5)) + event(post(3))));
      }})
      : new ReadableStream({start() {}}));
  }
  if (kind === "/stream") {
    if (scenario === "attach") return new Response(new ReadableStream({start() {}}));
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
    addEventListener: (type, fn) => { (docListeners[type] = docListeners[type] || []).push(fn); },
    body,
  },
  window: {addEventListener() {}},
  navigator: {onLine: true},
  sessionStorage: {getItem: (k) => storage.get(k) || null, setItem: (k, v) => storage.set(k, v)},
  localStorage: {getItem: (k) => storage.get(k) || null, setItem: (k, v) => storage.set(k, v)},
  // Handle suffixes (4 bytes) come from the deterministic queue; member keys (32 bytes) are 0xab.
  crypto: {getRandomValues(bytes) {
    if (bytes.length !== 4) { bytes.fill(0xab); return bytes; }
    const next = deterministicRandom.shift() || [0, 0, 0, 0]; bytes.set(next); return bytes;
  }},
  FormData: FakeFormData,
  fetch: fakeFetch,
  URL: {createObjectURL: (blob) => URL.createObjectURL(blob),
        revokeObjectURL: (url) => revoked.push(url)},
  setTimeout: (fn, ms) => setTimeout(fn, (ms || 0) / scale),
  setInterval: (fn) => { intervals.push(fn); return intervals.length; },
  Blob, TextDecoder, AbortController, clearTimeout, console,
};

function countdowns() {
  // The first "reconnecting in Ns" of each countdown is the backoff delay chosen.
  const starts = [];
  history.forEach((text, i) => {
    const match = /^board offline — retrying in (\d+)s$/.exec(text);
    if (match && !/^board offline/.test(history[i - 1] || "")) starts.push(Number(match[1]));
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
          revoked: revoked.slice(), countdowns: countdowns(), live, liveHistory: liveHistory.slice(),
          statusHistory: history.slice()};
}

const findAll = (pred) => created.filter(pred);
const button = (text) => findAll((node) => node.tagName === "BUTTON" && node.textContent === text);

async function exerciseAttachments() {
  const report = {};
  const img = created.find((node) => node.tagName === "IMG" && node.src);
  img.fire("click");
  report.lightboxOpen = !byId.lightbox.hidden;
  report.lightboxSrc = byId["lightbox-img"].src || null;
  report.lightboxSameUrl = report.lightboxSrc === img.src;
  report.lightboxName = byId["lightbox-name"].textContent;
  for (const fn of docListeners.keydown || []) fn({key: "Escape"});
  report.lightboxClosed = byId.lightbox.hidden && !byId["lightbox-img"].src;
  report.previewButtons = button("Preview").length;  // big.log (300 KB) gets none
  for (const toggle of button("Preview")) toggle.fire("click");
  await sleep(100);
  report.previews = findAll((node) => node.tagName === "PRE").map((node) => node.textContent);
  report.previewErrors = findAll((node) => /preview-err/.test(node.className || ""))
    .map((node) => node.textContent);
  const notesRow = findAll((node) => node.tagName === "PRE")[0].parent;
  const hide = notesRow.children.find((node) => node.textContent === "Hide");
  hide.fire("click");
  report.previewHidden = !notesRow.children.some((node) => node.tagName === "PRE");
  return report;
}

(async () => {
  vm.runInNewContext(script, context);
  await sleep(50);
  const first = snapshot();
  if (scenario === "main") {
    byId.token.value = " secret ";
    for (const fn of byId.auth.listeners.submit) fn({preventDefault() {}});
  }
  let compose = null;
  if (["compose", "collision", "compose-first-send"].includes(scenario)) {
    await sleep(40);
    byId["compose-text"].value = "draft text";
    byId["compose-text"].selectionStart = byId["compose-text"].value.length;
    byId["compose-text"].fire("input");
    byId.composer.fire("submit", {preventDefault() {}}); // opens inline identity form
    let identityCancelNoAutoSend = null;
    if (scenario !== "compose-first-send") {
      byId["identity-cancel"].fire("click");
      byId.identity.children[0].fire("click"); // Set name after cancelling the first-send prompt
      byId["identity-name"].value = scenario === "collision" ? "Alex" : "Web";
      byId["identity-form"].fire("submit", {preventDefault() {}});
      await sleep(15);
      identityCancelNoAutoSend = !requestDetails.some(
        (item) => item.path === "/posts" && item.method === "POST");
    }
    const firstPost = byId.posts.children[0];
    firstPost.children.find((node) => node.className === "reply").fire("click");
    byId["compose-text"].fire("input");
    byId["compose-text"].fire("keydown", {key: "Enter", preventDefault() {}});
    const pasted = {name: "paste.txt", size: 3};
    const attached = {name: "attach.txt", size: 4};
    byId["compose-text"].fire("paste", {clipboardData: {files: [pasted]}, preventDefault() {}});
    byId["file-input"].files = [attached]; byId["file-input"].fire("change");
    const beforeLimits = requestDetails.length;
    byId["compose-text"].value = "x".repeat(701); byId["compose-text"].fire("input");
    const over700Disabled = byId.send.disabled;
    const over700Count = byId.counter.textContent;
    byId["compose-text"].value = "   "; byId["compose-text"].fire("input");
    const whitespaceDisabled = byId.send.disabled;
    byId["file-input"].files = [{name: "3", size: 1}, {name: "4", size: 1}, {name: "5", size: 1}];
    byId["file-input"].fire("change");
    const fifthRefused = byId["composer-error"].textContent === "Choose no more than 4 files.";
    for (const chip of byId["file-chips"].children.slice().reverse()) chip.children[0].fire("click");
    byId["compose-text"].value = "draft text";
    byId["compose-text"].selectionStart = byId["compose-text"].value.length;
    byId["compose-text"].fire("input");
    byId["compose-text"].value = "@main draft text";
    byId["compose-text"].selectionStart = 5;
    byId["compose-text"].fire("input");
    const mentionOptions = byId.mentions.children.map((node) => node.textContent.slice(1));
    byId["compose-text"].fire("keydown", {key: "ArrowDown", preventDefault() {}});
    const mentionHighlight = byId.mentions.children.map((node) => node.dataset.active);
    byId["compose-text"].fire("keydown", {key: "Enter", preventDefault() {}});
    const limitRequests = requestDetails.slice(beforeLimits);
    byId["compose-text"].fire("paste", {clipboardData: {files: [pasted]}, preventDefault() {}});
    byId["file-input"].files = [attached]; byId["file-input"].fire("change");
    let sendLocked = null;
    if (scenario === "compose-first-send") {
      byId["identity-name"].value = "Web";
      byId["identity-form"].fire("submit", {preventDefault() {}});
    } else byId.composer.fire("submit", {preventDefault() {}});
    await sleep(5);
    if (byId["compose-text"].disabled) {
      const remove = byId["file-chips"].children[0].children[0];
      byId.posts.children[0].children.find((node) => node.className === "reply").fire("click");
      remove.fire("click");
      byId["compose-text"].fire("paste", {clipboardData: {files: [{name: "late", size: 1}]}, preventDefault() {}});
      for (const fn of docListeners.drop || []) fn({preventDefault() {},
        dataTransfer: {files: [{name: "late-drop", size: 1}]}});
      sendLocked = {text: byId["compose-text"].disabled, attach: byId.attach.disabled,
        fileInput: byId["file-input"].disabled, files: byId["file-chips"].children.length};
    }
    await sleep(120);
    const members = requestDetails.filter((item) => item.path === "/members" && item.method === "POST");
    const postRequest = requestDetails.find((item) => item.path === "/posts" && item.method === "POST");
    compose = {identity: postRequest && postRequest.body.author,
      member: members.length ? {kind: members[members.length - 1].body.kind,
        host: members[members.length - 1].body.host} : null,
      uploads: uploaded.slice(), posted: postRequest && postRequest.body,
      composerCleared: byId["compose-text"].value === "",
      identityCancelNoAutoSend, over700Count, sendLocked,
      mentionOptions, mentionHighlight, limitRequests: limitRequests.filter(
        (item) => item.path === "/members" || item.path === "/attachments" || item.path === "/posts"),
      limitDisabled: [over700Disabled, whitespaceDisabled, fifthRefused],
      limitErrors: ["Text must be 1 to 700 characters.", "Choose no more than 4 files.",
        "Text must be 1 to 700 characters."], requests: requestDetails.slice()};
    const beforeBeat = requestDetails.length;
    for (const beat of intervals) await beat();
    await sleep(20);
    compose.beat = requestDetails.slice(beforeBeat).map((item) => ({path: item.path,
      method: item.method, handle: item.body && item.body.handle, key: item.body && item.body.key}));
  } else if (scenario === "compose-outage") {
    await sleep(150);
    compose = {disabledOffline: byId.send.disabled && live === "0"};
  }
  let membersRace = null;
  if (scenario === "members-race") {
    await sleep(100);
    membersRace = {loads: requestDetails.filter((item) => item.path === "/members").length,
      ids: snapshot().ids};
  }
  await sleep(scenario === "eof" ? 1000 : scenario === "attach" ? 300 : 2000);
  const extra = scenario === "attach" ? await exerciseAttachments() : null;
  process.stdout.write(JSON.stringify({first, final: snapshot(), extra, compose, membersRace}));
  process.exit(0);
})().catch((err) => { console.error(err); process.exit(1); });
