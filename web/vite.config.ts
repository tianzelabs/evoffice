import { defineConfig } from "vite";

// `npm run dev` proxies the office's API, so the room can be developed against the live office.
const office = process.env.OFFICE_URL ?? "http://100.86.90.65:8710";
export default defineConfig({
  server: { proxy: Object.fromEntries(["/events", "/stream", "/say", "/me", "/price", "/bars", "/leaderboard", "/budget"]
    .map((p) => [p, { target: office, changeOrigin: true }])) },
  build: { outDir: "dist", chunkSizeWarningLimit: 2000 },
});
