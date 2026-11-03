import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The FastAPI token server (token_server.py) runs on port 8000.
    proxy: { "/token": "http://localhost:8000" },
  },
  build: {
    chunkSizeWarningLimit: 600, // livekit-client alone is ~560 kB minified
    rollupOptions: {
      output: { manualChunks: { livekit: ["livekit-client"], react: ["react", "react-dom"] } },
    },
  },
});
