import React, { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import type { Turn } from "../state";
import { ToolCard } from "./ToolCard";
import styles from "./Conversation.module.css";

interface Props {
  turns: Turn[];
  isRunning: boolean;
}

export function Conversation({ turns, isRunning }: Props): React.ReactElement {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  if (turns.length === 0) {
    return (
      <div className={styles.container}>
        <div className={styles.empty}>ready — type a task below</div>
      </div>
    );
  }

  return (
    <div className={styles.container} role="log" aria-live="polite" aria-label="Conversation">
      {turns.map((turn) => (
        <TurnView key={turn.index} turn={turn} />
      ))}
      {isRunning && <span className={styles.cursor} aria-hidden="true" />}
      <div ref={bottomRef} />
    </div>
  );
}

function TurnView({ turn }: { turn: Turn }): React.ReactElement {
  return (
    <div className={styles.turn}>
      {turn.thinking && (
        <div className={styles.thinking} aria-label="Agent thinking">
          {turn.thinking}
        </div>
      )}
      {turn.toolCalls.map((tc) => (
        <ToolCard key={tc.callId} toolCall={tc} />
      ))}
      {turn.text && (
        <div className={styles.markdown}>
          <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
            {turn.text}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
