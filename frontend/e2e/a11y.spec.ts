import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { authFile } from "./helpers";

// Automated WCAG 2.1 A/AA checks (axe). Fails on serious or critical violations. Automated checks are not a full audit.
const PAGES: Record<string, string[]> = {
  maya: ["/", "/cases", "/wallet", "/consent", "/rights", "/incidents", "/continuity", "/privacy", "/meetings", "/help", "/account", "/notifications"],
  lena: ["/authority", "/authority/queue"],
  govadmin: ["/governance", "/governance/audit", "/governance/risks"],
};
async function check(page: import("@playwright/test").Page) {
  await page.locator("h1").first().waitFor();
  await expect(page.locator(".loading")).toHaveCount(0, { timeout: 15_000 });
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
}
test("login page", async ({ page }) => {
  await page.goto("/login");
  await check(page);
});
test("public transparency", async ({ page }) => {
  await page.goto("/transparency");
  await check(page);
});
for (const [key, paths] of Object.entries(PAGES)) {
  test.describe(`${key} a11y`, () => {
    test.use({ storageState: authFile(key) });
    for (const p of paths) test(`${key} ${p}`, async ({ page }) => { await page.goto(p); await check(page); });
  });
}
test.describe("dark theme and Hebrew", () => {
  test.use({ storageState: authFile("maya"), colorScheme: "dark" });
  test("overview dark + rtl", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.setItem("cb.locale", "he"));
    await page.reload();
    await check(page);
    await page.evaluate(() => localStorage.setItem("cb.locale", "en"));
  });
});
