import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.join(here, "..", "backend");
const e2eDataDir = path.join(here, "..", "data", "e2e-playwright");
const externalBaseUrl = process.env.GEOSCOUT_E2E_BASE_URL;
const live = process.env.GEOSCOUT_E2E_LIVE === "1";
const python = process.env.GEOSCOUT_E2E_PYTHON || "python";
const apiPort = process.env.GEOSCOUT_E2E_API_PORT || "18000";
const apiUrl = `http://127.0.0.1:${apiPort}`;

function withEnv(extra: Record<string, string>) {
  const inherited: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value != null) inherited[key] = value;
  }
  return { ...inherited, ...extra };
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { baseURL: externalBaseUrl || "http://127.0.0.1:5173", trace: "on-first-retry" },
  webServer: externalBaseUrl
    ? undefined
    : [
        ...(!live
          ? [
              {
                command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${apiPort}`,
                cwd: backendDir,
                url: `${apiUrl}/api/health`,
                reuseExistingServer: false,
                timeout: 120_000,
                env: withEnv({
                  PYTHONPATH: backendDir,
                  GEOSCOUT_HOST: "127.0.0.1",
                  GEOSCOUT_PORT: apiPort,
                  GEOSCOUT_NCBI_MODE: "mock",
                  GEOSCOUT_LLM_MODE: "mock",
                  GEOSCOUT_EMBED_WORKER: "true",
                  GEOSCOUT_OPEN_BROWSER: "false",
                  GEOSCOUT_SERVE_WEB: "false",
                  GEOSCOUT_ALLOW_DEMO: "true",
                  GEOSCOUT_DATA_DIR: e2eDataDir,
                }),
              },
            ]
          : []),
        {
          command: "npm run preview",
          url: "http://127.0.0.1:5173",
          reuseExistingServer: !process.env.CI,
          env: withEnv({ GEOSCOUT_API_URL: live ? "http://127.0.0.1:8000" : apiUrl }),
        },
      ],
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
});
