import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * `base: "/app/"` because the built assets are served from that mount in production.
 * The dev proxy keeps the API same-origin, so no CORS middleware exists to go stale.
 * `/chat/{id}/events` is SSE: buffering it would defeat the point of streaming.
 *
 * Every API prefix has to be listed: anything missing here 404s in dev only, which is the
 * kind of bug that gets blamed on the endpoint rather than on this file.
 */
const API = "http://localhost:8000";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/auth", "/chat", "/conversations", "/dashboard", "/health", "/live"].map(
        (path) => [path, { target: API, changeOrigin: true }],
      ),
    ),
  },
});
