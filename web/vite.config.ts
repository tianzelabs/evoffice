import { defineConfig } from "vite";

const office = process.env.OFFICE_URL ?? "http://100.86.90.65:8710";
export default defineConfig({
  build: { outDir: "dist", emptyOutDir: true },
  server: { proxy: Object.fromEntries(["/events", "/stream", "/say", "/me", "/price", "/bars", "/leaderboard", "/budget", "/progress", "/employees", "/season", "/objective"].map((p) => [p, { target: office, changeOrigin: false }])) },
});
