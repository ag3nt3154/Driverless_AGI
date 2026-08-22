import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Composer } from "../renderer/components/Composer";
import { QuestionDialog } from "../renderer/components/QuestionDialog";

// ── Composer ──────────────────────────────────────────────────────────────────

describe("Composer", () => {
  it("shows Send button when idle", () => {
    render(<Composer status="idle" onSend={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: /send/i })).toBeInTheDocument();
  });

  it("Send is disabled with empty input", () => {
    render(<Composer status="idle" onSend={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("calls onSend with trimmed text on button click", async () => {
    const onSend = vi.fn();
    render(<Composer status="idle" onSend={onSend} onCancel={vi.fn()} />);
    const ta = screen.getByRole("textbox");
    await userEvent.type(ta, "  hello world  ");
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith("hello world");
  });

  it("clears input after send", async () => {
    const onSend = vi.fn();
    render(<Composer status="idle" onSend={onSend} onCancel={vi.fn()} />);
    const ta = screen.getByRole("textbox");
    await userEvent.type(ta, "task");
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(ta).toHaveValue("");
  });

  it("calls onSend on Enter key", async () => {
    const onSend = vi.fn();
    render(<Composer status="idle" onSend={onSend} onCancel={vi.fn()} />);
    const ta = screen.getByRole("textbox");
    await userEvent.type(ta, "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("does NOT send on Shift+Enter", async () => {
    const onSend = vi.fn();
    render(<Composer status="idle" onSend={onSend} onCancel={vi.fn()} />);
    const ta = screen.getByRole("textbox");
    await userEvent.type(ta, "hello{shift>}{Enter}{/shift}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("shows Cancel button and disables textarea when running", () => {
    render(<Composer status="running" onSend={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("calls onCancel when Cancel is clicked", () => {
    const onCancel = vi.fn();
    render(<Composer status="running" onSend={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("disables textarea when paused", () => {
    render(<Composer status="paused" onSend={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByRole("textbox")).toBeDisabled();
  });
});

// ── QuestionDialog ────────────────────────────────────────────────────────────

describe("QuestionDialog", () => {
  const question = {
    questionId: "q1",
    text: "Continue with the plan?",
    options: ["yes", "no"],
  };

  it("shows question text", () => {
    render(<QuestionDialog question={question} onAnswer={vi.fn()} />);
    expect(screen.getByText("Continue with the plan?")).toBeInTheDocument();
  });

  it("renders option buttons", () => {
    render(<QuestionDialog question={question} onAnswer={vi.fn()} />);
    expect(screen.getByRole("button", { name: "yes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "no" })).toBeInTheDocument();
  });

  it("calls onAnswer with questionId and chosen option", () => {
    const onAnswer = vi.fn();
    render(<QuestionDialog question={question} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "yes" }));
    expect(onAnswer).toHaveBeenCalledWith("q1", "yes");
  });

  it("shows free-text input when no options", () => {
    const q = { questionId: "q2", text: "What is your name?" };
    render(<QuestionDialog question={q} onAnswer={vi.fn()} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ok/i })).toBeInTheDocument();
  });

  it("submits free-text answer on OK click", async () => {
    const onAnswer = vi.fn();
    const q = { questionId: "q2", text: "Enter value:" };
    render(<QuestionDialog question={q} onAnswer={onAnswer} />);
    await userEvent.type(screen.getByRole("textbox"), "my answer");
    fireEvent.click(screen.getByRole("button", { name: /ok/i }));
    expect(onAnswer).toHaveBeenCalledWith("q2", "my answer");
  });

  it("submits free-text on Enter key", async () => {
    const onAnswer = vi.fn();
    const q = { questionId: "q2", text: "Enter value:" };
    render(<QuestionDialog question={q} onAnswer={onAnswer} />);
    await userEvent.type(screen.getByRole("textbox"), "answer{Enter}");
    expect(onAnswer).toHaveBeenCalledWith("q2", "answer");
  });

  it("has role=dialog for accessibility", () => {
    render(<QuestionDialog question={question} onAnswer={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
