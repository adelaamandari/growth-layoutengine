import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API is proxied in dev so the browser only ever talks to one
// origin -- no CORS preflight, and the same relative /api paths work
// unchanged in a production build behind a reverse proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
