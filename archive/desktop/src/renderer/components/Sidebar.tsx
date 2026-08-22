import React from "react";
import type { AgentStatus } from "../state";
import styles from "./Sidebar.module.css";

interface Props {
  status: AgentStatus;
  totalCostUsd: number;
  sessionTokens: number;
  planContent: string;
  onClear: () => void;
  onCompact: () => void;
}

export function Sidebar({
  status,
  totalCostUsd,
  sessionTokens,
  planContent,
  onClear,
  onCompact,
}: Props): React.ReactElement {
  const isIdle = status === "idle";

  return (
    <aside className={styles.sidebar} aria-label="Sidebar">
      <div className={styles.section}>
        <span className={styles.label}>Status</span>
        <span className={styles.value}>
          <span className={styles.statusDot} data-status={status} aria-hidden="true" />
          {status}
        </span>
      </div>

      <div className={styles.section}>
        <span className={styles.label}>Session cost</span>
        <span className={styles.value}>${totalCostUsd.toFixed(4)}</span>
      </div>

      <div className={styles.section}>
        <span className={styles.label}>Tokens</span>
        <span className={styles.value}>{sessionTokens.toLocaleString()}</span>
      </div>

      <div className={styles.section}>
        <button
          className={styles.btn}
          onClick={onCompact}
          disabled={!isIdle}
          title="Compact conversation history"
        >
          Compact
        </button>
        <button
          className={styles.btn}
          onClick={onClear}
          disabled={!isIdle}
          title="Clear conversation and start fresh"
        >
          Clear
        </button>
      </div>

      {planContent && (
        <div className={styles.plan} aria-label="Plan">
          {planContent}
        </div>
      )}
    </aside>
  );
}
