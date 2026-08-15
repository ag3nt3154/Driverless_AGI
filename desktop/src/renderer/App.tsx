import React from "react";

/**
 * Root application shell.
 * Layout, routing, and state wiring are added in Tasks 9-11.
 */
export function App(): React.ReactElement {
  return (
    <div style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center" }}>
      <p style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
        DAGI — initialising…
      </p>
    </div>
  );
}
