import { describe, expect, it } from "vitest";
import { connectionPayload, defaultConn, matchProvider } from "./Connect";
import { nextRunId, runOwnedByProject, safeHost, totalTokens } from "./testable";

it("includes output tokens even when input tokens are zero", () => {
  expect(totalTokens({ prompt_tokens: 0, completion_tokens: 2048 })).toBe(2048);
  expect(totalTokens({ prompt_tokens: 100, completion_tokens: 2048, estimated: true })).toBe(2148);
});

describe("url host display", () => {
  it("parses openai host", () => {
    expect(safeHost("https://api.openai.com/v1")).toBe("api.openai.com");
  });
  it("parses deepseek host", () => {
    expect(safeHost("https://api.deepseek.com")).toBe("api.deepseek.com");
  });
});

describe("connection payload", () => {
  it("omits empty keys so a retest does not wipe memory", () => {
    const body = connectionPayload({ ...defaultConn, llm_base_url: "https://api.example.com", ncbi_email: "a@b.c" });
    expect(body).not.toHaveProperty("llm_api_key");
    expect(body).not.toHaveProperty("ncbi_api_key");
    expect(body.ncbi_email).toBe("a@b.c");
    expect(body.llm_base_url).toBe("https://api.example.com");
  });
  it("matches common provider URLs", () => {
    expect(matchProvider("https://api.openai.com/v1")).toBe("openai");
    expect(matchProvider("https://api.deepseek.com/")).toBe("deepseek");
    expect(matchProvider("https://other.example/v1")).toBe("custom");
    expect(matchProvider("")).toBe("");
  });
});

describe("project run stickiness", () => {
  it("clears the run when the topic has none", () => {
    expect(nextRunId([], "run-a")).toBeNull();
    expect(nextRunId(undefined, "run-a")).toBeNull();
  });
  it("keeps a run that belongs to the topic and otherwise selects the latest", () => {
    expect(nextRunId([{ id: "b" }, { id: "a" }], "a")).toBe("a");
    expect(nextRunId([{ id: "b" }], "a")).toBe("b");
  });
  it("rejects export targets from another topic", () => {
    expect(runOwnedByProject({ id: "r1", project_id: "A" }, "B")).toBe(false);
    expect(runOwnedByProject({ id: "r1", project_id: "A" }, "A")).toBe(true);
  });
});
