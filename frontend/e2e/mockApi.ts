import type { Page } from "@playwright/test";

export type MockProject = {
  id: string;
  name: string;
  original_request: string;
  spec: Record<string, unknown>;
  runs: MockRun[];
};

export type MockRun = {
  id: string;
  project_id: string;
  status: string;
  stage: string;
  mode: string;
  gse: string;
  title: string;
};

const emptySpec = {
  original_request: "",
  disease: [],
  tissues: [],
  organisms: ["Homo sapiens"],
  assay_types: ["rna_seq_generic"],
  assay_methods: [],
  required_groups: ["case", "control"],
  minimum_donors_per_group: null,
  preferred_metadata: [],
  processed_matrix_requirement: "preferred",
  inclusion_criteria: [],
  unresolved_questions: [],
};

export function seedProjects(): MockProject[] {
  return [
    {
      id: "proj-a",
      name: "topic A",
      original_request: "topic A Alzheimer",
      spec: { ...emptySpec, original_request: "topic A Alzheimer" },
      runs: [{ id: "run-a", project_id: "proj-a", status: "completed", stage: "exporting", mode: "full", gse: "GSEAAA", title: "A only" }],
    },
    {
      id: "proj-b",
      name: "topic B",
      original_request: "topic B empty",
      spec: { ...emptySpec, original_request: "topic B empty" },
      runs: [],
    },
    {
      id: "proj-c",
      name: "topic C",
      original_request: "topic C diabetes",
      spec: { ...emptySpec, original_request: "topic C diabetes" },
      runs: [{ id: "run-c", project_id: "proj-c", status: "completed", stage: "exporting", mode: "full", gse: "GSECCC", title: "C only" }],
    },
  ];
}

export async function installMockApi(page: Page, projects: MockProject[], log: { exportRunIds: string[] }) {
  const created: MockProject[] = [...projects];
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    if (path === "/api/health") {
      return route.fulfill({ json: { ok: true, version: "0.1.1", ncbi_mode: "mock", llm_mode: "mock", demo: false, host: "127.0.0.1" } });
    }
    if (path === "/api/connections" && method === "GET") {
      return route.fulfill({ json: { llm_key_present: false, llm_base_url: "", llm_model: "", ncbi_email: "" } });
    }
    if (path === "/api/budget-presets") {
      return route.fulfill({ json: { low: { max_unique_gse: 80, max_deep_verify: 0, max_tokens: 20000, max_runtime_s: 600 }, medium: { max_unique_gse: 150, max_deep_verify: 6, max_tokens: 150000, max_runtime_s: 1800 }, high: { max_unique_gse: 400, max_deep_verify: 20, max_tokens: 600000, max_runtime_s: 5400 }, ultra: { max_unique_gse: 1500, max_deep_verify: 100, max_tokens: 4000000, max_runtime_s: 21600 } } });
    }
    if (path === "/api/projects" && method === "GET") {
      return route.fulfill({ json: created.map((p) => ({ id: p.id, name: p.name, original_request: p.original_request, spec: p.spec })) });
    }
    if (path === "/api/projects" && method === "POST") {
      const body = req.postDataJSON() as { original_request: string; name?: string };
      const id = `proj-${created.length + 1}`;
      const project: MockProject = { id, name: body.name || body.original_request.slice(0, 40), original_request: body.original_request, spec: { ...emptySpec, original_request: body.original_request }, runs: [] };
      created.push(project);
      return route.fulfill({ json: { id: project.id, name: project.name, spec: project.spec } });
    }
    const specSave = path.match(/^\/api\/projects\/([^/]+)\/spec$/);
    if (specSave && method === "PUT") {
      return route.fulfill({ json: { ok: true } });
    }
    const runsList = path.match(/^\/api\/projects\/([^/]+)\/runs$/);
    if (runsList && method === "GET") {
      const project = created.find((p) => p.id === runsList[1]);
      return route.fulfill({ json: (project?.runs || []).map(runView) });
    }
    if (runsList && method === "POST") {
      const project = created.find((p) => p.id === runsList[1]);
      const run: MockRun = { id: `run-${Date.now()}`, project_id: project?.id || runsList[1], status: "completed", stage: "exporting", mode: "manual_query", gse: "GSE1000", title: "mock hit" };
      project?.runs.unshift(run);
      return route.fulfill({ json: runView(run) });
    }
    const runGet = path.match(/^\/api\/runs\/([^/]+)$/);
    if (runGet && method === "GET") {
      const run = created.flatMap((p) => p.runs).find((r) => r.id === runGet[1]);
      if (!run) return route.fulfill({ status: 404, json: { detail: "missing" } });
      return route.fulfill({ json: runView(run) });
    }
    const queries = path.match(/^\/api\/runs\/([^/]+)\/queries$/);
    if (queries) {
      return route.fulfill({ json: [{ round_no: 1, term: "mock", hit_count: 1, new_unique_gse: 1, status: "searched", query_translation: "mock" }] });
    }
    const datasets = path.match(/^\/api\/runs\/([^/]+)\/datasets$/);
    if (datasets && method === "GET") {
      const run = created.flatMap((p) => p.runs).find((r) => r.id === datasets[1]);
      const items = run ? [{ gse: run.gse, title: run.title, taxon: "Homo sapiens", gdstype: "RNA-seq", category: url.searchParams.get("category") || "needs_review", reason: "mock" }] : [];
      return route.fulfill({ json: { total: items.length, items } });
    }
    const detail = path.match(/^\/api\/runs\/([^/]+)\/datasets\/([^/]+)$/);
    if (detail && method === "GET") {
      return route.fulfill({ json: { gse: detail[2], dataset: { title: "mock", summary: "", taxon: "Homo sapiens", gdstype: "RNA-seq" }, run_dataset: { category: "excluded", reason: "mock", applicable_gsms: [] }, samples: [], assessments: [] } });
    }
    const exp = path.match(/^\/api\/runs\/([^/]+)\/exports$/);
    if (exp && method === "POST") {
      log.exportRunIds.push(exp[1]);
      return route.fulfill({ json: { id: "exp1", filename: "out.xlsx", download: "/api/exports/exp1/file", complete: true, status: "done" } });
    }
    if (path === "/api/exports/exp1/file") {
      return route.fulfill({
        status: 200,
        headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Content-Disposition": "attachment; filename=out.xlsx" },
        body: "xlsx",
      });
    }
    if (path.startsWith("/api/connections") && method !== "GET") {
      return route.fulfill({ json: { ok: false, message: "mock has no live model" } });
    }
    const control = path.match(/^\/api\/runs\/([^/]+)\/(pause|resume|cancel)$/);
    if (control && method === "POST") {
      return route.fulfill({ json: { ok: true } });
    }
    return route.fulfill({ status: 404, json: { detail: path } });
  });
}

function runView(run: MockRun) {
  return {
    id: run.id,
    project_id: run.project_id,
    mode: run.mode,
    status: run.status,
    stage: run.stage,
    stop_reason: "",
    counters: { queries_done: 1, unique_gse: 1 },
    token_usage: {},
    budget: { max_unique_gse: 40 },
    error_message: "",
    spec: emptySpec,
  };
}
