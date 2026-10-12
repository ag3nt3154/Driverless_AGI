// rpa/drivers/outline.js — dagi's own page outline, injected via execute_script.
//
// Returns a flat array of {i, role, name, id, testid, value, bbox, secure,
// interactive, path}. Firefox's WebDriver-computed aria_role/accessible_name
// are empty for date/password inputs, so this walk computes its own role and
// name instead of relying on the browser's accessibility tree (S0 finding).
//
// bbox is [left, top, right, bottom], viewport-relative (same frame the
// browser driver's bbox matching and click-by-coords use).
//
// Side effect: every element included in the output is tagged with
// data-dagi-i="<i>" so the driver can map a WebElement (from find_element(s))
// or a freshly re-run outline back to the exact Element this script produced
// at index i, without relying on bbox/role re-matching (which breaks on
// duplicate elements, e.g. two identical "OK" buttons).
//
// Selenium's execute_script wraps this whole file's text in its own function
// body, so a top-level `return out;` (no IIFE) is what hands the array back.
var IMPLICIT = {
  A: "link", BUTTON: "button", SELECT: "combobox", TEXTAREA: "textbox",
  H1: "heading", H2: "heading", H3: "heading", NAV: "navigation",
  FORM: "form", OPTION: "option", IMG: "img",
};
var INTERACTIVE_ROLES = {
  link: 1, button: 1, textbox: 1, password: 1, file: 1, date: 1,
  combobox: 1, checkbox: 1, radio: 1, option: 1,
};

function dagiRole(el) {
  var r = el.getAttribute("role");
  if (r) return r;
  if (el.tagName === "INPUT") {
    var t = el.type || "text";
    return (
      { checkbox: "checkbox", radio: "radio", button: "button", submit: "button",
        file: "file", password: "password", date: "date" }[t] || "textbox"
    );
  }
  return IMPLICIT[el.tagName] || null;
}

function dagiFileInputName(el) {
  // S0 gap: plain <input type=file> gets no accessible name from the generic
  // rules below (no innerText, no useful attrs) — fall back through
  // aria-label -> associated <label> -> name attr -> "Browse…".
  var a = el.getAttribute("aria-label");
  if (a) return a;
  if (el.id) {
    var l = document.querySelector('label[for="' + el.id + '"]');
    if (l) return l.innerText.trim();
  }
  var pl = el.closest("label");
  if (pl && pl !== el) return pl.innerText.trim();
  if (el.name) return el.name;
  return "Browse…";
}

function dagiName(el) {
  if (el.tagName === "INPUT" && el.type === "file") return dagiFileInputName(el);
  var a = el.getAttribute("aria-label");
  if (a) return a;
  var lb = el.getAttribute("aria-labelledby");
  if (lb) {
    return lb
      .split(" ")
      .map(function (id) {
        var t = document.getElementById(id);
        return t ? t.innerText : "";
      })
      .join(" ")
      .trim();
  }
  if (el.id) {
    var l = document.querySelector('label[for="' + el.id + '"]');
    if (l) return l.innerText.trim();
  }
  var pl = el.closest("label");
  if (pl && pl !== el) return pl.innerText.trim();
  if (["BUTTON", "A", "H1", "H2", "H3", "OPTION"].indexOf(el.tagName) !== -1) {
    return el.innerText.trim();
  }
  return (
    el.getAttribute("title") ||
    el.getAttribute("alt") ||
    el.getAttribute("placeholder") ||
    ""
  );
}

function dagiAncestorPath(el) {
  var parts = [];
  var node = el.parentElement;
  while (node) {
    var r = dagiRole(node);
    if (r) parts.push(r + ":" + dagiName(node));
    node = node.parentElement;
  }
  parts.reverse();
  return parts;
}

var out = [];
var i = 0;
var all = document.querySelectorAll("*");
for (var idx = 0; idx < all.length; idx++) {
  var el = all[idx];
  var r = dagiRole(el);
  if (!r) continue;
  var b = el.getBoundingClientRect();
  var cs = getComputedStyle(el);
  if (cs.visibility === "hidden" || cs.display === "none") continue;
  // Not checked (v1): aria-hidden="true"; ancestors with display:none are caught by zero size.
  if (b.width === 0 && b.height === 0 && r !== "file") continue;

  var secure = el.type === "password";
  var hasChildElements = r === "button" || r === "link" ? false : el.children && el.children.length > 0;
  var interactive = !!INTERACTIVE_ROLES[r] && !hasChildElements;

  var elemIndex = i++;
  el.setAttribute("data-dagi-i", String(elemIndex));
  out.push({
    i: elemIndex,
    role: r,
    name: dagiName(el).slice(0, 60),
    id: el.id || null,
    testid: el.dataset ? el.dataset.testid || null : null,
    value: secure
      ? "[secure]"
      : el.value !== undefined && el.tagName !== "BUTTON"
      ? String(el.value).slice(0, 40)
      : null,
    bbox: [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)],
    secure: secure,
    interactive: interactive,
    path: dagiAncestorPath(el),
  });
}
return out;
