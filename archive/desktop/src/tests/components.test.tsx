import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ToolCard } from "../renderer/components/ToolCard";
import { Conversation } from "../renderer/components/Conversation";
import type { ToolCall, Turn } from "../renderer/state";

// ── ToolCard ──────────────────────────────────────────────────────────────────

function makeToolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    callId: "c1",
    tool: "bash",
    input: { command: "ls" },
    startedAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("ToolCard", () => {
  it("shows tool name", () => {
    render(<ToolCard toolCall={makeToolCall()} />);
    expect(screen.getByText("bash")).toBeInTheDocument();
  });

  it("is collapsed by default", () => {
    render(<ToolCard toolCall={makeToolCall()} />);
    expect(screen.queryByText(/"command"/)).toBeNull();
  });

  it("expands on click", () => {
    render(<ToolCard toolCall={makeToolCall()} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/"command"/)).toBeInTheDocument();
  });

  it("shows success indicator when result is present", () => {
    render(<ToolCard toolCall={makeToolCall({ result: "ok" })} />);
    expect(screen.getByText("✓")).toBeInTheDocument();
  });

  it("shows error indicator when is_error is true", () => {
    render(<ToolCard toolCall={makeToolCall({ result: "fail", isError: true })} />);
    expect(screen.getByText("✗")).toBeInTheDocument();
  });

  it("shows result content when expanded", () => {
    render(<ToolCard toolCall={makeToolCall({ result: "file.txt" })} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("file.txt")).toBeInTheDocument();
  });
});

// ── Conversation ──────────────────────────────────────────────────────────────

function makeTurn(overrides: Partial<Turn> = {}): Turn {
  return {
    index: 1,
    text: "",
    thinking: "",
    toolCalls: [],
    complete: false,
    ...overrides,
  };
}

describe("Conversation", () => {
  it("shows empty state when no turns", () => {
    render(<Conversation turns={[]} isRunning={false} />);
    expect(screen.getByText(/ready/i)).toBeInTheDocument();
  });

  it("renders turn text as markdown", () => {
    const turn = makeTurn({ text: "**hello**" });
    render(<Conversation turns={[turn]} isRunning={false} />);
    expect(screen.getByRole("log")).toBeInTheDocument();
    // ReactMarkdown renders **hello** as a <strong> element
    expect(screen.getByText("hello").tagName).toBe("STRONG");
  });

  it("renders thinking text", () => {
    const turn = makeTurn({ thinking: "reasoning..." });
    render(<Conversation turns={[turn]} isRunning={false} />);
    expect(screen.getByText("reasoning...")).toBeInTheDocument();
  });

  it("renders tool cards for each tool call", () => {
    const turn = makeTurn({
      toolCalls: [
        makeToolCall({ callId: "c1", tool: "bash" }),
        makeToolCall({ callId: "c2", tool: "read" }),
      ],
    });
    render(<Conversation turns={[turn]} isRunning={false} />);
    expect(screen.getByText("bash")).toBeInTheDocument();
    expect(screen.getByText("read")).toBeInTheDocument();
  });

  it("shows blinking cursor when running", () => {
    render(<Conversation turns={[makeTurn()]} isRunning={true} />);
    // cursor is aria-hidden, but still in DOM
    const cursors = document.querySelectorAll("[aria-hidden='true']");
    expect(cursors.length).toBeGreaterThan(0);
  });

  it("does not show cursor when idle", () => {
    render(<Conversation turns={[makeTurn({ text: "done" })]} isRunning={false} />);
    const cursors = document.querySelectorAll("[aria-hidden='true']");
    expect(cursors.length).toBe(0);
  });
});
