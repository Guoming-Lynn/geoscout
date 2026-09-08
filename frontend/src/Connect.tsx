import { HelpCircle } from "lucide-react";
import { useState } from "react";
import { api } from "./api/client";
import { LanguageSelect, useI18n } from "./i18n";
import { safeHost } from "./testable";

export type Conn = {
  llm_base_url: string;
  llm_model: string;
  llm_api_key: string;
  ncbi_email: string;
  ncbi_api_key: string;
};

export const COMMON_PROVIDERS = [
  { id: "openai", label: "OpenAI", url: "https://api.openai.com/v1" },
  { id: "deepseek", label: "DeepSeek", url: "https://api.deepseek.com" },
  { id: "openrouter", label: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  { id: "groq", label: "Groq", url: "https://api.groq.com/openai/v1" },
  { id: "together", label: "Together AI", url: "https://api.together.xyz/v1" },
  { id: "mistral", label: "Mistral", url: "https://api.mistral.ai/v1" },
  { id: "xai", label: "xAI", url: "https://api.x.ai/v1" },
  { id: "moonshot", label: "Moonshot / Kimi", url: "https://api.moonshot.cn/v1" },
  { id: "qwen", label: "Qwen (DashScope)", url: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { id: "siliconflow", label: "SiliconFlow", url: "https://api.siliconflow.cn/v1" },
  { id: "ollama", label: "Ollama (local)", url: "http://127.0.0.1:11434/v1" },
  { id: "lmstudio", label: "LM Studio (local)", url: "http://127.0.0.1:1234/v1" },
] as const;

export function matchProvider(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, "");
  const hit = COMMON_PROVIDERS.find((p) => p.url.replace(/\/+$/, "") === trimmed);
  return hit ? hit.id : trimmed ? "custom" : "";
}

export const defaultConn: Conn = {
  llm_base_url: "",
  llm_model: "",
  llm_api_key: "",
  ncbi_email: "",
  ncbi_api_key: "",
};

export const WORKBENCH_FLAG = "geoscout.workbench";

export function connectionPayload(conn: Conn): Record<string, unknown> {
  const body: Record<string, unknown> = {
    llm_base_url: conn.llm_base_url.trim(),
    llm_model: conn.llm_model.trim(),
    ncbi_email: conn.ncbi_email.trim() || null,
  };
  if (conn.llm_api_key.trim()) body.llm_api_key = conn.llm_api_key;
  if (conn.ncbi_api_key.trim()) body.ncbi_api_key = conn.ncbi_api_key;
  return body;
}

export function rememberWorkbench() {
  try {
    sessionStorage.setItem(WORKBENCH_FLAG, "1");
  } catch {
    /* ignore */
  }
}

export function forgetWorkbench() {
  try {
    sessionStorage.removeItem(WORKBENCH_FLAG);
  } catch {
    /* ignore */
  }
}

export function hadWorkbench(): boolean {
  try {
    return sessionStorage.getItem(WORKBENCH_FLAG) === "1";
  } catch {
    return false;
  }
}

export function ConnectionFields({
  conn,
  onChange,
}: {
  conn: Conn;
  onChange: (next: Conn) => void;
}) {
  const { t } = useI18n();
  const [help, setHelp] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [fetching, setFetching] = useState(false);
  const [fetchMsg, setFetchMsg] = useState("");

  async function fetchModels() {
    setFetching(true);
    setFetchMsg("");
    try {
      const result = (await api.listModels(connectionPayload(conn))) as {
        ok?: boolean;
        models?: string[];
        message?: string;
      };
      const list = result.models || [];
      setModels(list);
      setFetchMsg(result.message || "");
      if (list.length && !conn.llm_model) {
        onChange({ ...conn, llm_model: list[0] });
      }
    } catch (e) {
      setFetchMsg((e as Error).message);
    } finally {
      setFetching(false);
    }
  }

  return (
    <div className="stack">
      <label>
        <span className="label-row">
          {t("baseUrl")}
          <button
            type="button"
            className="icon-btn"
            aria-label={t("help")}
            onClick={() => setHelp((v) => !v)}
          >
            <HelpCircle size={16} />
          </button>
        </span>
        <select
          aria-label={t("provider")}
          value={matchProvider(conn.llm_base_url)}
          onChange={(e) => {
            const id = e.target.value;
            if (id === "custom" || id === "") {
              if (matchProvider(conn.llm_base_url) !== "custom") {
                onChange({ ...conn, llm_base_url: "" });
              }
              return;
            }
            const hit = COMMON_PROVIDERS.find((p) => p.id === id);
            if (hit) onChange({ ...conn, llm_base_url: hit.url });
          }}
        >
          <option value="">{t("chooseProvider")}</option>
          {COMMON_PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
          <option value="custom">{t("customUrl")}</option>
        </select>
        <input
          value={conn.llm_base_url}
          onChange={(e) => onChange({ ...conn, llm_base_url: e.target.value })}
          aria-label={t("baseUrl")}
          placeholder="https://api.openai.com/v1"
        />
      </label>
      {conn.llm_base_url.trim() && (
        <p className="muted">
          {t("requestHost")}
          {safeHost(conn.llm_base_url)}
        </p>
      )}
      {help && <div className="help-card">{t("helpBody")}</div>}
      <label>
        {t("apiKey")}
        <input
          type="password"
          autoComplete="new-password"
          value={conn.llm_api_key}
          onChange={(e) => onChange({ ...conn, llm_api_key: e.target.value })}
          aria-label={t("apiKey")}
        />
      </label>
      <label>
        {t("modelName")}
        <div className="row">
          <input
            value={conn.llm_model}
            onChange={(e) => onChange({ ...conn, llm_model: e.target.value })}
            aria-label={t("modelName")}
          />
          <button
            type="button"
            className="secondary"
            disabled={fetching || !conn.llm_base_url.trim() || !conn.llm_api_key.trim()}
            onClick={() => void fetchModels()}
          >
            {fetching ? t("fetchingModels") : t("fetchModels")}
          </button>
        </div>
      </label>
      {models.length > 0 && (
        <label>
          {t("pickModel")}
          <select
            value={models.includes(conn.llm_model) ? conn.llm_model : ""}
            onChange={(e) => onChange({ ...conn, llm_model: e.target.value })}
            aria-label={t("pickModel")}
          >
            <option value="">{t("pickModel")}</option>
            {models.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      )}
      {fetchMsg && <p className="muted">{fetchMsg}</p>}
      <label>
        {t("ncbiEmail")}
        <input
          value={conn.ncbi_email}
          onChange={(e) => onChange({ ...conn, ncbi_email: e.target.value })}
          aria-label={t("ncbiEmail")}
        />
      </label>
      <label>
        {t("ncbiKey")}
        <input
          type="password"
          autoComplete="new-password"
          value={conn.ncbi_api_key}
          onChange={(e) => onChange({ ...conn, ncbi_api_key: e.target.value })}
          aria-label={t("ncbiKey")}
        />
      </label>
    </div>
  );
}

export const AUTHOR_NAME = "Guoming Lin";
export const AUTHOR_URL = "https://github.com/Guoming-Lynn";

export function AuthorCredit() {
  return (
    <p className="author">
      Author:{" "}
      <a href={AUTHOR_URL} target="_blank" rel="noreferrer">
        {AUTHOR_NAME}
      </a>
    </p>
  );
}

export function ConnectGate({
  conn,
  onChange,
  onReady,
  version,
}: {
  conn: Conn;
  onChange: (next: Conn) => void;
  onReady: (mode: "model" | "ncbi") => void;
  version: string;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function startWithModel() {
    setBusy(true);
    setMessage("");
    try {
      const body = connectionPayload(conn);
      await api.saveConnections(body);
      const result = (await api.testConnections(body)) as { ok?: boolean; message?: string };
      if (result.ok === false) {
        setMessage(result.message || t("testConn"));
        return;
      }
      onChange({ ...conn, llm_api_key: "", ncbi_api_key: "" });
      rememberWorkbench();
      onReady("model");
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <div className="gate-card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <p className="muted">v{version}</p>
          <LanguageSelect />
        </div>
        <h1>GEOScout</h1>
        <p className="muted">{t("tagline")}</p>
        <ConnectionFields conn={conn} onChange={onChange} />
        {message && (
          <p className="error" role="alert">
            {message}
          </p>
        )}
        <div className="stack" style={{ marginTop: 8 }}>
          <button disabled={busy || !conn.llm_api_key.trim() || !conn.llm_base_url.trim()} onClick={() => void startWithModel()}>
            {busy ? t("testing") : t("testStart")}
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => {
              rememberWorkbench();
              onReady("ncbi");
            }}
          >
            {t("ncbiOnly")}
          </button>
        </div>
        <AuthorCredit />
      </div>
    </div>
  );
}
