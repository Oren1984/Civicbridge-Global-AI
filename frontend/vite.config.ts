import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API and LiveKit signalling to a running stack (docker compose up).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8084",
      "/rtc": { target: "ws://localhost:8084", ws: true },
    },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 900 },
});
