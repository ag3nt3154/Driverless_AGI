import React, { useReducer, useEffect, useCallback } from "react";
import { dagiReducer, initialState } from "./state";
import { Conversation } from "./components/Conversation";
import { Composer } from "./components/Composer";
import { QuestionDialog } from "./components/QuestionDialog";
import { Sidebar } from "./components/Sidebar";
import { parseSlash } from "./slash";
import { serializeCommand } from "@shared/protocol";
import type { SidecarEvent } from "@shared/protocol";

// ── IPC helpers ───────────────────────────────────────────────────────────────

function sendCmd(type: string, extras: Record<string, unknown> = {}): void {
  const line = serializeCommand(type as any, extras);
  const payload = JSON.parse(line);
  window.dagiAPI?.send("dagi:command", payload);
}

// ── Layout styles (inline — no extra CSS file needed for the shell) ───────────

const shell: React.CSSProperties = {
  display: "flex",
  height: "100vh",
  overflow: "hidden",
};

const main: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
};

// ── App ───────────────────────────────────────────────────────────────────────

export function App(): React.ReactElement {
  const [state, dispatch] = useReducer(dagiReducer, initialState);

  // ── Subscribe to sidecar events via IPC ──────────────────────────────────

  useEffect(() => {
    if (!window.dagiAPI) return;

    const unsub = window.dagiAPI.on("dagi:event", (payload: unknown) => {
      dispatch({ type: "sidecar_event", event: payload as SidecarEvent });
    });

    return unsub;
  }, []);

  // ── Command handlers ──────────────────────────────────────────────────────

  const handleSend = useCallback(
    (task: string) => {
      const slash = parseSlash(task);
      if (slash) {
        switch (slash.name) {
          case "compact":
            sendCmd("compact");
            break;
          case "clear":
            dispatch({ type: "clear" });
            sendCmd("clear");
            break;
          case "cancel":
            sendCmd("cancel");
            dispatch({ type: "set_status", status: "idle" });
            break;
          case "model":
            if (slash.args) sendCmd("set_model", { model_id: slash.args });
            break;
          case "skill":
            if (slash.args) sendCmd("invoke_skill", { skill_name: slash.args });
            break;
          case "workflow":
            if (slash.args) sendCmd("invoke_workflow", { workflow_name: slash.args });
            break;
          case "history":
            sendCmd("list_history");
            break;
          case "help":
            // TODO: show help overlay (Task 11)
            break;
        }
        return;
      }
      sendCmd("run", { task });
    },
    []
  );

  const handleCancel = useCallback(() => {
    sendCmd("cancel");
    dispatch({ type: "set_status", status: "idle" });
  }, []);

  const handleAnswer = useCallback((questionId: string, answer: string) => {
    sendCmd("answer_question", { question_id: questionId, answer });
    dispatch({ type: "set_status", status: "running" });
  }, []);

  const handleClear = useCallback(() => {
    dispatch({ type: "clear" });
    sendCmd("clear");
  }, []);

  const handleCompact = useCallback(() => {
    sendCmd("compact");
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={shell}>
      <Sidebar
        status={state.status}
        totalCostUsd={state.totalCostUsd}
        sessionTokens={state.sessionTokens}
        planContent={state.planContent}
        onClear={handleClear}
        onCompact={handleCompact}
      />

      <div style={main}>
        <Conversation
          turns={state.turns}
          isRunning={state.status === "running"}
        />
        <Composer
          status={state.status}
          onSend={handleSend}
          onCancel={handleCancel}
        />
      </div>

      {state.question && (
        <QuestionDialog question={state.question} onAnswer={handleAnswer} />
      )}
    </div>
  );
}
