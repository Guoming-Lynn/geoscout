import { describe, expect, it } from "vitest";
import { safeHost } from "./testable";

describe("url host display", () => {
  it("parses openai host", () => {
    expect(safeHost("https://api.openai.com/v1")).toBe("api.openai.com");
  });
});
