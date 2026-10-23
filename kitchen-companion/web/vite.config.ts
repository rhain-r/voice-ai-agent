import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the bot server runs separately on :7860; in production it serves this build itself.
export default defineConfig({
  plugins: [react()],
  // The WebRTC client and its media helpers are one ~700 kB chunk; there's nothing to split off.
  build: { chunkSizeWarningLimit: 800 },
  server: {
    port: 5173,
    host: true,
    proxy: { "/api": "http://localhost:7860" },
  },
});
