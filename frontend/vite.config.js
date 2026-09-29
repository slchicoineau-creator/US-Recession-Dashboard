import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE / VITE_OUT_DIR are set only by tools/export_static.py for the
// read-only snapshot build (e.g. base "/recession-dashboard/" on GitHub Pages).
// The default build (dist/, served by Flask) is unchanged.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:5000",
    },
  },
  build: {
    outDir: process.env.VITE_OUT_DIR || "dist",
    emptyOutDir: true,
  },
});
