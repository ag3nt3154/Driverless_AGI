// @vitest-environment node
import { describe, it, expect } from "vitest";
import { parseSlash, matchingCommands, SLASH_DEFINITIONS } from "../renderer/slash";

describe("parseSlash", () => {
  it("returns null for plain text", () => {
    expect(parseSlash("hello world")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(parseSlash("")).toBeNull();
  });

  it("returns null for unknown slash command", () => {
    expect(parseSlash("/bogus")).toBeNull();
  });

  it("parses /compact with no args", () => {
    const cmd = parseSlash("/compact");
    expect(cmd?.name).toBe("compact");
    expect(cmd?.args).toBe("");
  });

  it("parses /clear", () => {
    expect(parseSlash("/clear")?.name).toBe("clear");
  });

  it("parses /cancel", () => {
    expect(parseSlash("/cancel")?.name).toBe("cancel");
  });

  it("parses /model with arg", () => {
    const cmd = parseSlash("/model claude-opus-4-7");
    expect(cmd?.name).toBe("model");
    expect(cmd?.args).toBe("claude-opus-4-7");
  });

  it("parses /skill with name arg", () => {
    const cmd = parseSlash("/skill memory-query");
    expect(cmd?.name).toBe("skill");
    expect(cmd?.args).toBe("memory-query");
  });

  it("parses /workflow with name", () => {
    const cmd = parseSlash("/workflow my-flow");
    expect(cmd?.name).toBe("workflow");
    expect(cmd?.args).toBe("my-flow");
  });

  it("parses /history", () => {
    expect(parseSlash("/history")?.name).toBe("history");
  });

  it("parses /help", () => {
    expect(parseSlash("/help")?.name).toBe("help");
  });

  it("trims surrounding whitespace", () => {
    expect(parseSlash("  /compact  ")?.name).toBe("compact");
  });

  it("trims args", () => {
    const cmd = parseSlash("/model   claude-sonnet-4-6   ");
    expect(cmd?.args).toBe("claude-sonnet-4-6");
  });

  it("handles /model with multi-word args", () => {
    const cmd = parseSlash("/model claude opus");
    expect(cmd?.name).toBe("model");
    expect(cmd?.args).toBe("claude opus");
  });
});

describe("matchingCommands", () => {
  it("returns all commands for empty prefix", () => {
    expect(matchingCommands("").length).toBe(SLASH_DEFINITIONS.length);
  });

  it("returns all commands for bare /", () => {
    expect(matchingCommands("/").length).toBe(SLASH_DEFINITIONS.length);
  });

  it("filters by prefix", () => {
    const matches = matchingCommands("c");
    const names = matches.map((d) => d.name);
    expect(names).toContain("compact");
    expect(names).toContain("clear");
    expect(names).toContain("cancel");
    expect(names).not.toContain("model");
  });

  it("returns single match for full name", () => {
    const matches = matchingCommands("compact");
    expect(matches.length).toBe(1);
    expect(matches[0].name).toBe("compact");
  });

  it("is case-insensitive", () => {
    expect(matchingCommands("C").length).toBeGreaterThan(0);
  });

  it("returns empty for non-matching prefix", () => {
    expect(matchingCommands("zzz")).toHaveLength(0);
  });
});
