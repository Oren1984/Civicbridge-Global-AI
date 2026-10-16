import path from "node:path";
import { test, type Page } from "@playwright/test";
import { authFile, REPO } from "./helpers";

// Documentation screenshots of the running application. Run on demand: CB_SCREENSHOTS=1 npx playwright test screenshots
test.skip(!process.env.CB_SCREENSHOTS, "set CB_SCREENSHOTS=1 to capture documentation screenshots");

const OUT = path.join(REPO, "docs", "screenshots");
const shot = async (page: Page, name: string) => {
  await page.locator(".loading").first().waitFor({ state: "detached", timeout: 15_000 }).catch(() => undefined);
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
};

test.describe("citizen", () => {
  test.use({ storageState: authFile("maya"), viewport: { width: 1360, height: 900 } });
  test("citizen screens", async ({ page }) => {
    await page.goto("/");
    await shot(page, "01-citizen-overview");
    await page.goto("/cases");
    await page.getByRole("link", { name: /relocation|Relocation|Umzug|Berlin/ }).first().click();
    await shot(page, "02-case-checklist");
    await page.getByRole("tab", { name: /Requests/ }).click();
    await shot(page, "03-case-requests");
    await page.goto("/wallet");
    await shot(page, "04-wallet");
    await page.goto("/consent");
    await shot(page, "05-consent-centre");
    await page.goto("/rights");
    await shot(page, "06-rights-navigator");
    await page.goto("/incidents?new=1");
    await shot(page, "07-incident-report");
    await page.goto("/continuity");
    await shot(page, "08-continuity");
    await page.goto("/help");
    await shot(page, "09-help-center");
  });
});

test.describe("citizen hebrew", () => {
  test.use({ storageState: authFile("maya"), viewport: { width: 1360, height: 900 } });
  test("rtl overview", async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.setItem("cb.locale", "he"));
    await page.reload();
    await shot(page, "10-citizen-overview-hebrew-rtl");
    await page.evaluate(() => localStorage.setItem("cb.locale", "en"));
  });
});

test.describe("mobile", () => {
  test.use({ storageState: authFile("maya"), viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  test("mobile overview", async ({ page }) => {
    await page.goto("/");
    await page.locator("h1").first().waitFor();
    await page.locator(".loading").first().waitFor({ state: "detached", timeout: 15_000 }).catch(() => undefined);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, "11-mobile-overview.png") });
    await page.getByRole("button", { name: "Open menu" }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, "11b-mobile-menu.png") });
  });
});

test.describe("authority", () => {
  test.use({ storageState: authFile("lena"), viewport: { width: 1360, height: 900 } });
  test("authority screens", async ({ page }) => {
    await page.goto("/authority");
    await shot(page, "12-authority-dashboard");
    await page.goto("/authority/queue");
    await shot(page, "13-authority-queue");
    await page.locator("table a.mono").first().click();
    await shot(page, "14-authority-request-review");
  });
});

test.describe("governance", () => {
  test.use({ storageState: authFile("govadmin"), viewport: { width: 1360, height: 900 } });
  test("governance screens", async ({ page }) => {
    await page.goto("/governance");
    await shot(page, "15-governance-overview");
    await page.goto("/governance/audit");
    await page.getByRole("button", { name: "Verify chain" }).click();
    await page.getByText("Chain intact").waitFor();
    await shot(page, "16-governance-audit-verified");
    await page.goto("/governance/integrations");
    await shot(page, "17-governance-integrations");
  });
});

test("public transparency", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/transparency");
  await shot(page, "18-public-transparency");
  await page.goto("/login");
  await shot(page, "00-login");
});
