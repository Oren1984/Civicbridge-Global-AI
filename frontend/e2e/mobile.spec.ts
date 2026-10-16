import { expect, test } from "@playwright/test";
import { authFile } from "./helpers";

// Phone width (390 px): no horizontal page scroll on the main pages of each workspace.
const PAGES: Record<string, string[]> = {
  maya: ["/", "/cases", "/wallet", "/consent", "/rights", "/incidents", "/continuity", "/meetings", "/help", "/account"],
  lena: ["/authority", "/authority/queue"],
  govadmin: ["/governance", "/governance/audit"],
};
for (const [key, paths] of Object.entries(PAGES)) {
  test.describe(`${key} mobile`, () => {
    test.use({ storageState: authFile(key), viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    for (const p of paths) {
      test(`${key} ${p} fits 390px`, async ({ page }) => {
        await page.goto(p);
        await page.locator("h1").first().waitFor();
        await expect(page.locator(".loading")).toHaveCount(0, { timeout: 15_000 });
        const [sw, cw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
        expect(sw, `page is ${sw}px wide in a ${cw}px viewport`).toBeLessThanOrEqual(cw);
      });
    }
  });
}
