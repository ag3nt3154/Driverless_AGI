import React, { useState } from "react";
import type { ToolCall } from "../state";
import styles from "./ToolCard.module.css";

interface Props {
  toolCall: ToolCall;
}

export function ToolCard({ toolCall }: Props): React.ReactElement {
  const [open, setOpen] = useState(false);
  const { tool, input, result, isError } = toolCall;

  const inputText = JSON.stringify(input, null, 2);
  const hasResult = result !== undefined;

  return (
    <div className={styles.card} role="region" aria-label={`Tool: ${tool}`}>
      <div
        className={styles.header}
        onClick={() => setOpen((o) => !o)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className={styles.toolName} data-tool={tool.toLowerCase()}>
          {tool}
        </span>
        {hasResult && (
          <span style={{ color: isError ? "var(--text-error)" : "var(--text-success)", marginLeft: "var(--sp-2)" }}>
            {isError ? "✗" : "✓"}
          </span>
        )}
        <span className={`${styles.chevron} ${open ? styles.open : ""}`}>▶</span>
      </div>
      {open && (
        <div className={styles.body}>
          <pre className={styles.pre}>{inputText}</pre>
          {hasResult && (
            <>
              <hr style={{ border: "none", borderTop: "1px solid var(--border-subtle)", margin: "var(--sp-2) 0" }} />
              <pre className={`${styles.pre} ${isError ? styles.error : ""}`}>{result}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
