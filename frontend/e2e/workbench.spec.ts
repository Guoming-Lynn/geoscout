import { expect, test } from "@playwright/test";

test("workbench renders and settings are labeled", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "GEOScout" })).toBeVisible();
  await page.getByRole("button", { name: "打开设置" }).click();
  await expect(page.getByText("请求将发往")).toBeVisible();
  await expect(page.getByLabel("课题描述")).toBeVisible();
});

test("manual search, status, detail, excel, empty and error states", async ({ page }) => {
  test.setTimeout(90_000);
  const health = await page.request.get("http://127.0.0.1:8000/api/health").catch(() => null);
  test.skip(!health || !health.ok(), "API not running on 127.0.0.1:8000");
  await page.goto("/");
  await page.getByLabel("课题描述").fill("human atherosclerosis scRNA-seq");
  await page.getByRole("button", { name: "创建课题" }).click();
  await expect(page.getByText("NCBI：")).toBeVisible();
  await expect(page.getByRole("button", { name: "真实/当前 NCBI 模式检索" })).toBeEnabled({ timeout: 15_000 });
  await page.getByLabel("手工 GEO 检索式").fill('GSE1000[Accession] AND "gse"[ETYP]');
  await page.getByRole("button", { name: "真实/当前 NCBI 模式检索" }).click();
  await expect(page.getByText("阶段")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/完成|部分完成|运行中|排队/)).toBeVisible({ timeout: 60_000 });
  const gseCell = page.getByRole("cell", { name: "GSE1000" });
  await expect(gseCell).toBeVisible({ timeout: 60_000 });
  await gseCell.click();
  await expect(page.getByRole("heading", { name: /详情/ })).toBeVisible();
  await page.getByRole("button", { name: /导出 Excel/ }).click();
  await page.getByRole("button", { name: "打开设置" }).click();
  await page.getByRole("button", { name: "测试连接" }).click();
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 10_000 });
});
