import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView — provide a no-op
if (typeof window !== "undefined") {
  window.HTMLElement.prototype.scrollIntoView = function () {};
}
