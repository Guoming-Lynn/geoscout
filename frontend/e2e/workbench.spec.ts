import { expect, test } from "@playwright/test";
import { installMockApi } from "./mockApi";

async function enterWorkbench(page: import("@playwright/test").Page) {
  await page.goto("/");
  const skip = page.getByRole("button", { name: "Enter with NCBI search only" });
  const settings = page.getByRole("button", { name: "Open settings" });
  await expect(skip.or(settings)).toBeVisible({ timeout: 15_000 });
  if (await skip.isVisible()) {
    await skip.click();
  }
}

test("startup shows connection gate then NCBI skip enters workbench", async ({ page }) => {
  if (process.env.GEOSCOUT_E2E_LIVE !== "1") {
    await installMockApi(page, [], { exportRunIds: [] });
  }
  await page.goto("/");
  const skip = page.getByRole("button", { name: "Enter with NCBI search only" });
  const settings = page.getByRole("button", { name: "Open settings" });
  await expect(skip.or(settings)).toBeVisible({ timeout: 15_000 });
  if (await skip.isVisible()) {
    await expect(page.getByText("v0.1.1")).toBeVisible();
    await expect(page.getByRole("button", { name: "Test connection and start" })).toBeDisabled();
    await expect(page.getByLabel("Model API key")).toBeVisible();
    await expect(page.getByLabel("Provider")).toBeVisible();
    await expect(page.getByRole("link", { name: "Guoming Lin" })).toHaveAttribute(
      "href",
      "https://github.com/Guoming-Lynn",
    );
    await skip.click();
  }
  await expect(settings).toBeVisible();
});

test("workbench renders and settings are labeled", async ({ page }) => {
  if (process.env.GEOSCOUT_E2E_LIVE !== "1") {
    await installMockApi(page, [], { exportRunIds: [] });
  }
  await enterWorkbench(page);
  await expect(page.getByRole("heading", { name: "GEOScout" })).toBeVisible();
  await page.getByRole("combobox", { name: "Sample source", exact: true }).selectOption("primary");
  await expect(page.getByRole("combobox", { name: "Sample source", exact: true })).toHaveValue("primary");
  await page.getByLabel("Require tissue match", { exact: true }).check();
  await page.getByLabel("Deep review limit", { exact: true }).fill("12");
  await expect(page.getByLabel("Deep review limit", { exact: true })).toHaveValue("12");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: `test-results/source-controls-${test.info().project.name}.png`, fullPage: true });
  await expect(page.getByRole("button", { name: "Start review" })).toBeVisible();
  const intensity = page.getByRole("combobox", { name: "Review intensity" });
  await expect(intensity).toHaveValue("medium");
  await expect(intensity.locator("option")).toHaveText(["Low", "Medium", "High", "Ultra"]);
  await intensity.selectOption("ultra");
  await expect(intensity).toHaveValue("ultra");
  await page.getByRole("button", { name: "Open settings" }).click();
  await expect(page.getByLabel("Model base URL")).toBeVisible();
  await expect(page.getByLabel("Topic")).toBeVisible();
});

test("manual search, status, detail, excel, empty and error states", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const live = process.env.GEOSCOUT_E2E_LIVE === "1";
  if (live) {
    const health = await page.request.get("http://127.0.0.1:8000/api/health").catch(() => null);
    test.skip(!health || !health.ok(), "Live NCBI e2e requires a running API on 127.0.0.1:8000");
  }
  await enterWorkbench(page);
  await page.getByLabel("Topic").fill("human atherosclerosis scRNA-seq");
  await page.getByRole("button", { name: "Create topic" }).click();
  await expect(page.getByText(/NCBI:/)).toBeVisible();
  await page.getByLabel("Manual English search (no model key)").fill('GSE1000[Accession] AND "gse"[ETYP]');
  await expect(page.getByRole("button", { name: "Search in current NCBI mode" })).toBeEnabled({ timeout: 15_000 });
  await page.getByRole("button", { name: "Search in current NCBI mode" }).click();
  await expect(page.getByRole("status")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("status")).toContainText(/Starting|Queued|Running|Completed|Partial/, { timeout: 60_000 });
  await expect(page.getByRole("status")).toContainText(/Completed|Partial/, { timeout: 60_000 });
  const gseCell = page.getByRole("cell", { name: /^GSE\d+$/ }).first();
  for (const tab of ["Needs review", "Excluded", "Recommended"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    if (await gseCell.isVisible().catch(() => false)) {
      break;
    }
  }
  await expect(gseCell).toBeVisible({ timeout: live ? 60_000 : 15_000 });
  await gseCell.click();
  await expect(page.getByRole("heading", { name: /GSE\d+.*Details/ })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /Export Excel/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
  const saved = await download.path();
  expect(saved).toBeTruthy();
  const buf = await import("node:fs/promises").then((fs) => fs.readFile(saved!));
  expect(buf.subarray(0, 2).toString()).toBe("PK");
  expect(buf.byteLength).toBeGreaterThan(1000);
  await page.getByRole("button", { name: "Open settings" }).click();
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: testInfo.outputPath("workbench.png"), fullPage: true });
});
