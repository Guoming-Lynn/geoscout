import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxy = {
  "/api": {
    target: process.env.GEOSCOUT_API_URL || "http://127.0.0.1:8000",
    timeout: 120_000,
    proxyTimeout: 120_000,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    proxy: apiProxy,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
