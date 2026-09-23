export type ResearchSpec = {
  original_request: string;
  disease: string[];
  tissues: string[];
  tissue_required?: boolean;
  sample_source?: string;
  organisms: string[];
  assay_types: string[];
  assay_methods?: string[];
  required_groups: string[];
  minimum_donors_per_group: number | null;
  preferred_metadata: string[];
  processed_matrix_requirement: string;
  inclusion_criteria: { criterion_id: string; field: string; description: string; user_text: string; priority: string }[];
  unresolved_questions: string[];
};

export type RunView = {
  id: string;
  project_id: string;
  mode: string;
  status: string;
  stage: string;
  stop_reason: string;
  counters: Record<string, number>;
  token_usage: Record<string, number | boolean>;
  budget: Record<string, number>;
  error_message: string;
  spec: ResearchSpec;
};

const DEFAULT_TIMEOUT_MS = 12_000;
const LLM_TIMEOUT_MS = 90_000;

function timeoutSignal(ms: number): AbortSignal {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    return AbortSignal.timeout(ms);
  }
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

export function formatApiError(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
      try {
        return JSON.stringify(item);
      } catch {
        return "";
      }
    }).filter(Boolean);
    return parts.join("; ") || fallback;
  }
  try {
    return JSON.stringify(body);
  } catch {
    return fallback;
  }
}

async function req<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { timeoutMs, headers, signal, ...rest } = (init || {}) as RequestInit & { timeoutMs?: number };
  const method = String(rest.method || "GET").toUpperCase();
  const merged = new Headers(headers);
  if (method !== "GET" && method !== "HEAD" && !merged.has("Content-Type")) {
    merged.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(path, {
      credentials: "include",
      ...rest,
      headers: merged,
      signal: signal ?? timeoutSignal(timeoutMs ?? DEFAULT_TIMEOUT_MS),
    });
  } catch (err) {
    const name = err instanceof DOMException ? err.name : err instanceof Error ? err.name : "";
    if (name === "AbortError" || name === "TimeoutError") {
    throw new Error("api_timeout");
    }
    throw err;
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = formatApiError(await res.json(), detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  budgetPresets: () => req<Record<string, Record<string, number>>>("/api/budget-presets"),
  health: () => req<{ ok: boolean; version: string; ncbi_mode: string; llm_mode: string; demo: boolean }>("/api/health"),
  connections: () => req<Record<string, unknown>>("/api/connections"),
  saveConnections: (body: Record<string, unknown>) => req("/api/connections", { method: "PUT", body: JSON.stringify(body) }),
  testConnections: (body: Record<string, unknown>) =>
    req("/api/connections/test", { method: "POST", body: JSON.stringify(body), timeoutMs: LLM_TIMEOUT_MS }),
  listModels: (body: Record<string, unknown>) =>
    req<{ ok?: boolean; models?: string[]; message?: string }>("/api/connections/models", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: LLM_TIMEOUT_MS,
    }),
  clearWorkspace: () => req<{ ok: boolean }>("/api/workspace/clear", { method: "POST" }),
  projects: () => req<{ id: string; name: string; original_request: string; spec: ResearchSpec; parse_token_usage?: Record<string, number | boolean> }[]>("/api/projects"),
  createProject: (original_request: string, name?: string) =>
    req<{ id: string; name: string; spec: ResearchSpec }>("/api/projects", { method: "POST", body: JSON.stringify({ original_request, name }) }),
  parseSpec: (id: string) =>
    req<{ spec: ResearchSpec; questions: string[] }>(`/api/projects/${id}/spec/parse`, { method: "POST", timeoutMs: LLM_TIMEOUT_MS }),
  saveSpec: (id: string, spec: ResearchSpec) => req(`/api/projects/${id}/spec`, { method: "PUT", body: JSON.stringify(spec) }),
  createRun: (id: string, body: Record<string, unknown>) => req<RunView>(`/api/projects/${id}/runs`, { method: "POST", body: JSON.stringify(body) }),
  listRuns: (id: string) => req<RunView[]>(`/api/projects/${id}/runs`),
  getRun: (id: string) => req<RunView>(`/api/runs/${id}`),
  pause: (id: string) => req(`/api/runs/${id}/pause`, { method: "POST" }),
  resume: (id: string) => req(`/api/runs/${id}/resume`, { method: "POST" }),
  cancel: (id: string) => req(`/api/runs/${id}/cancel`, { method: "POST" }),
  queries: (id: string) => req<{ term: string; round_no: number; hit_count: number | null; new_unique_gse: number; status: string; query_translation: string }[]>(`/api/runs/${id}/queries`),
  datasets: (id: string, category?: string, offset = 0, limit = 50) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    params.set("offset", String(offset));
    params.set("limit", String(limit));
    return req<{ total: number; items: Record<string, unknown>[] }>(`/api/runs/${id}/datasets?${params.toString()}`);
  },
  dataset: (id: string, gse: string) => req<Record<string, unknown>>(`/api/runs/${id}/datasets/${gse}`),
  override: (id: string, gse: string, category: string, reason: string) =>
    req(`/api/runs/${id}/datasets/${gse}/override`, { method: "POST", body: JSON.stringify({ category, reason }) }),
  exportRun: (id: string) =>
    req<{ id: string; filename: string; download: string; complete: boolean; status: string }>(`/api/runs/${id}/exports`, {
      method: "POST",
      body: JSON.stringify({ include_json: true }),
      timeoutMs: 60_000,
    }),
};
