import { expect, test } from "@playwright/test";
import { installMockApi, seedProjects } from "./mockApi";

async function enterWorkbench(page: import("@playwright/test").Page) {
  await page.goto("/");
  const skip = page.getByRole("button", { name: "Enter with NCBI search only" });
  const settings = page.getByRole("button", { name: "Open settings" });
  await expect(skip.or(settings)).toBeVisible({ timeout: 15_000 });
  if (await skip.isVisible()) {
    await skip.click();
  }
}

test("switching topics does not keep the previous run or export target", async ({ page }) => {
  const log = { exportRunIds: [] as string[] };
  await installMockApi(page, seedProjects(), log);
  await enterWorkbench(page);
  await page.getByRole("button", { name: "topic A" }).click();
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "topic B" }).click();
  await expect(page.getByLabel("Topic")).toHaveValue(/topic B/);
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Export Excel/ })).toHaveCount(0);
  await page.getByRole("button", { name: "topic C" }).click();
  await expect(page.getByRole("cell", { name: "GSECCC", exact: true })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Export Excel/ }).click();
  await download;
  expect(log.exportRunIds).toEqual(["run-c"]);
});

test("creating a topic and rapid switching do not export the previous run", async ({ page }) => {
  const log = { exportRunIds: [] as string[] };
  await installMockApi(page, seedProjects(), log);
  await enterWorkbench(page);
  await page.getByRole("button", { name: "topic A" }).click();
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toBeVisible();
  await page.getByLabel("Topic").fill("brand new topic");
  await page.getByRole("button", { name: "Create topic" }).click();
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Export Excel/ })).toHaveCount(0);
  await page.getByRole("button", { name: "topic A" }).click();
  await page.getByRole("button", { name: "topic B" }).click();
  await page.getByRole("button", { name: "topic C" }).click();
  await expect(page.getByRole("cell", { name: "GSECCC", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toHaveCount(0);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Export Excel/ }).click();
  await download;
  expect(log.exportRunIds.at(-1)).toBe("run-c");
});
