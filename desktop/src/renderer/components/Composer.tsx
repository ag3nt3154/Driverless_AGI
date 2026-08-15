import React, { useRef, useState, useCallback, KeyboardEvent } from "react";
import type { AgentStatus } from "../state";
import styles from "./Composer.module.css";

interface Props {
  status: AgentStatus;
  onSend: (task: string) => void;
  onCancel: () => void;
}

export function Composer({ status, onSend, onCancel }: Props): React.ReactElement {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isRunning = status === "running";
  const isPaused = status === "paused";
  const canSend = !isRunning && !isPaused && text.trim().length > 0;

  const submit = useCallback(() => {
    const task = text.trim();
    if (!task || isRunning || isPaused) return;
    setText("");
    onSend(task);
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }, [text, isRunning, isPaused, onSend]);

  const handleKey = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submit();
      }
    },
    [submit]
  );

  const autoResize = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    setText(el.value);
  }, []);

  return (
    <div>
      {isRunning && (
        <div className={styles.hint}>running — press Cancel to stop</div>
      )}
      <div className={styles.bar}>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          value={text}
          onChange={autoResize}
          onKeyDown={handleKey}
          disabled={isRunning || isPaused}
          placeholder={
            isPaused ? "agent is paused…" :
            isRunning ? "agent is running…" :
            "Enter a task (Shift+Enter for newline)"
          }
          rows={1}
          aria-label="Task input"
        />
        {isRunning ? (
          <button className={styles.cancelBtn} onClick={onCancel} aria-label="Cancel">
            Cancel
          </button>
        ) : (
          <button
            className={styles.sendBtn}
            onClick={submit}
            disabled={!canSend}
            aria-label="Send task"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
