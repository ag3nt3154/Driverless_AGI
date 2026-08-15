import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@shared": path.resolve(__dirname, "src/shared"),
      "@main": path.resolve(__dirname, "src/main"),
      "@renderer": path.resolve(__dirname, "src/renderer"),
    },
  },
  test: {
    // Per-file environment overrides via // @vitest-environment node|jsdom comments
    environment: "jsdom",
    setupFiles: ["src/tests/setup.ts"],
    globals: true,
  },
});
