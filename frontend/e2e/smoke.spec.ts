import { expect, test } from "@playwright/test";
import { authFile, watch } from "./helpers";

// Every navigation entry of every workspace renders without uncaught errors or server errors.
const PAGES: Record<string, string[]> = {
  maya: ["/", "/journeys", "/cases", "/wallet", "/consent", "/delegations", "/rights", "/translations", "/incidents", "/meetings", "/continuity", "/privacy", "/notifications", "/account", "/help", "/help/video-meetings", "/transparency"],
  lena: ["/authority", "/authority/queue", "/authority/consents", "/meetings", "/notifications"],
  thomas: ["/authority", "/authority/queue", "/authority/notices"],
  amir: ["/authority", "/authority/incidents"],
  petra: ["/institution", "/cases"],
  david: ["/professional", "/cases", "/translations"],
  rina: ["/professional", "/meetings"],
  govadmin: ["/governance", "/governance/audit", "/governance/policies", "/governance/risks", "/governance/incidents", "/governance/integrations", "/governance/jobs", "/governance/quality", "/governance/reporting", "/governance/ai"],
  viewer: ["/", "/cases", "/wallet"],
};

for (const [key, paths] of Object.entries(PAGES)) {
  test.describe(`${key} pages`, () => {
    test.use({ storageState: authFile(key) });
    for (const p of paths) {
      test(`${key} ${p}`, async ({ page }) => {
        const problems = watch(page);
        await page.goto(p);
        await expect(page.locator("h1").first()).toBeVisible();
        await expect(page.locator(".loading")).toHaveCount(0, { timeout: 15_000 });
        await expect(page.getByText("Something went wrong")).toHaveCount(0);
        expect(problems).toEqual([]);
      });
    }
  });
}
