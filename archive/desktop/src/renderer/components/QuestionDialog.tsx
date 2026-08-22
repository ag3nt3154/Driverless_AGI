import React, { useState, useCallback, KeyboardEvent } from "react";
import type { QuestionPrompt } from "../state";
import styles from "./QuestionDialog.module.css";

interface Props {
  question: QuestionPrompt;
  onAnswer: (questionId: string, answer: string) => void;
}

export function QuestionDialog({ question, onAnswer }: Props): React.ReactElement {
  const [freeText, setFreeText] = useState("");
  const { questionId, text, options } = question;

  const submit = useCallback(
    (answer: string) => {
      if (answer.trim()) onAnswer(questionId, answer.trim());
    },
    [questionId, onAnswer]
  );

  const handleFreeKey = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") submit(freeText);
    },
    [freeText, submit]
  );

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Agent question">
      <div className={styles.dialog}>
        <p className={styles.text}>{text}</p>
        {options && options.length > 0 ? (
          <div className={styles.options}>
            {options.map((opt) => (
              <button
                key={opt}
                className={styles.optionBtn}
                onClick={() => submit(opt)}
              >
                {opt}
              </button>
            ))}
          </div>
        ) : (
          <div className={styles.freeInput}>
            <input
              className={styles.input}
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              onKeyDown={handleFreeKey}
              placeholder="Type your answer…"
              autoFocus
              aria-label="Answer"
            />
            <button
              className={styles.submitBtn}
              onClick={() => submit(freeText)}
              disabled={!freeText.trim()}
            >
              OK
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
