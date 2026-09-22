import { expect, test, type Page } from "@playwright/test";
import { installMockApi, seedProjects } from "./mockApi";

async function enterWorkbench(page: Page) {
  await page.goto("/");
  const skip = page.getByRole("button", { name: "Enter with NCBI search only" });
  const settings = page.getByRole("button", { name: "Open settings" });
  await expect(skip.or(settings)).toBeVisible({ timeout: 15_000 });
  if (await skip.isVisible()) {
    await skip.click();
  }
}

async function sidebar(page: Page, open: boolean) {
  await page.locator(".app").waitFor();
  const mobile = await page.evaluate(() => window.matchMedia("(max-width: 900px)").matches);
  if (!mobile) return;
  const toggle = page.getByRole("button", { name: "Toggle sidebar" });
  await expect(toggle).toBeVisible();
  const drawer = page.locator("aside.sidebar");
  const shown = async () => {
    const box = await drawer.boundingBox();
    return !!box && box.x >= -1;
  };
  if ((await shown()) === open) return;
  await toggle.click();
  await expect.poll(shown, { timeout: 5_000 }).toBe(open);
}

test("switching topics does not keep the previous run or export target", async ({ page }) => {
  const log = { exportRunIds: [] as string[] };
  await installMockApi(page, seedProjects(), log);
  await enterWorkbench(page);
  await sidebar(page, true);
  await page.getByRole("button", { name: "topic A" }).click();
  await sidebar(page, false);
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toBeVisible();
  await sidebar(page, true);
  await page.getByRole("button", { name: "topic B" }).click();
  await sidebar(page, false);
  await expect(page.getByLabel("Topic")).toHaveValue(/topic B/);
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Export Excel/ })).toHaveCount(0);
  await sidebar(page, true);
  await page.getByRole("button", { name: "topic C" }).click();
  await sidebar(page, false);
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
  await sidebar(page, true);
  await page.getByRole("button", { name: "topic A" }).click();
  await sidebar(page, false);
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toBeVisible();
  await page.getByLabel("Topic").fill("brand new topic");
  await page.getByRole("button", { name: "Create topic" }).click();
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Export Excel/ })).toHaveCount(0);
  await sidebar(page, true);
  await page.getByRole("button", { name: "topic A" }).click();
  await page.getByRole("button", { name: "topic B" }).click();
  await page.getByRole("button", { name: "topic C" }).click();
  await sidebar(page, false);
  await expect(page.getByRole("cell", { name: "GSECCC", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "GSEAAA", exact: true })).toHaveCount(0);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Export Excel/ }).click();
  await download;
  expect(log.exportRunIds.at(-1)).toBe("run-c");
});
