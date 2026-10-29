import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on loopback only; /api is proxied to the backend (contract R1: the backend
// allows this origin through its dev_allowed_origins setting). Production: the backend
// serves dist/ itself, same origin, no proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8790", changeOrigin: false },
    },
  },
  build: { outDir: "dist", sourcemap: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
