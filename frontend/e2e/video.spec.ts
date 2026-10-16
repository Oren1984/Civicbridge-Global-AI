import { expect, test, type Browser, type Page } from "@playwright/test";
import path from "node:path";
import { authFile, REPO, watch } from "./helpers";

// Journey F: real LiveKit media between three browsers with fake camera/microphone devices.
// Host (resident) opens; authority officer and interpreter wait, are admitted and connect; the interpreter is removed
// while connected and must actually be disconnected from the media server.

async function as(browser: Browser, key: string) {
  const ctx = await browser.newContext({ storageState: authFile(key), permissions: ["camera", "microphone"] });
  const page = await ctx.newPage();
  return { page, problems: watch(page), close: () => ctx.close() };
}
const api = (page: Page, method: string, url: string) =>
  page.evaluate(async ([m, u]) => {
    const me = await (await fetch("/api/auth/me")).json();
    const r = await fetch(u, { method: m, headers: { "X-CSRF-Token": me.csrf_token, "Content-Type": "application/json" }, body: m === "GET" ? undefined : "{}" });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, [method, url] as const);

test("F: waiting room, admission, media, per-viewer documents, removal of a connected participant, end", async ({ browser }) => {
  test.setTimeout(240_000);
  const title = `E2E consultation ${Date.now()}`;
  const maya = await as(browser, "maya");

  // Schedule from the seeded relocation case, inviting the case officer and the interpreter.
  await maya.page.goto("/cases");
  await maya.page.getByRole("link", { name: "Relocate from Israel to Berlin, Germany" }).first().click();
  const caseUrl = maya.page.url();
  await maya.page.getByRole("button", { name: "Schedule a meeting" }).click();
  const dlg = maya.page.getByRole("dialog");
  await dlg.getByLabel("Title").fill(title);
  await dlg.locator("label.check", { hasText: "Lena Fischer" }).locator("input").check();
  await dlg.locator("label.check", { hasText: "Rina Adler" }).locator("input").check();
  await dlg.getByRole("button", { name: "Schedule", exact: true }).click();
  await expect(maya.page.locator(".toasts")).toContainText("Meeting scheduled");

  // Host opens and connects.
  await maya.page.goto("/meetings");
  await maya.page.getByRole("link", { name: title }).click();
  const meetingUrl = maya.page.url();
  const mid = meetingUrl.split("/").pop()!;
  await maya.page.getByRole("button", { name: "Open meeting" }).click();
  await maya.page.getByRole("button", { name: "Connect" }).click();
  await expect(maya.page.locator(".video-grid .tile")).toHaveCount(1, { timeout: 20_000 });

  // Officer and interpreter ask to join and wait.
  const lena = await as(browser, "lena");
  const rina = await as(browser, "rina");
  for (const u of [lena, rina]) {
    await u.page.goto(meetingUrl);
    await u.page.getByRole("button", { name: "Ask to join" }).click();
    await expect(u.page.getByText("The host will admit you.")).toBeVisible();
    // A waiting participant cannot get a media token.
    expect((await api(u.page, "POST", `/api/meetings/${mid}/token`)).status).toBe(403);
  }

  // Host admits both; both connect and media flows.
  for (const name of ["Lena Fischer", "Rina Adler"]) {
    const row = maya.page.locator(".list > li", { hasText: name }).filter({ has: maya.page.getByRole("button", { name: "Admit" }) });
    await row.getByRole("button", { name: "Admit" }).click({ timeout: 10_000 });
    await expect(maya.page.locator(".toasts")).toContainText("Participant admitted");
  }
  for (const u of [lena, rina]) {
    await u.page.getByRole("button", { name: "Connect" }).click({ timeout: 10_000 });
  }
  for (const u of [maya, lena, rina]) await expect(u.page.locator(".video-grid .tile")).toHaveCount(3, { timeout: 30_000 });
  // Remote video actually plays (frames decoded from the fake camera).
  await expect.poll(() => lena.page.evaluate(() => Array.from(document.querySelectorAll(".tile video")).filter((v) => (v as HTMLVideoElement).videoWidth > 0).length), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);

  if (process.env.CB_SCREENSHOTS) {
    await maya.page.setViewportSize({ width: 1360, height: 900 });
    await maya.page.waitForTimeout(1500);
    await maya.page.screenshot({ path: path.join(REPO, "docs", "screenshots", "19-video-consultation-three-participants.png") });
  }

  // Interpreter has meeting access only: the case itself stays closed to them.
  const rinaCase = await api(rina.page, "GET", `/api/cases/${caseUrl.split("/").pop()}`);
  expect([403, 404]).toContain(rinaCase.status);

  // Host shares a document: the authority (consent) can open it, the interpreter cannot.
  await maya.page.getByRole("button", { name: "Share a document" }).click();
  await maya.page.getByRole("dialog").locator(".list > li", { hasText: "Passport (synthetic)" }).first().getByRole("button", { name: "Share" }).click();
  await expect(maya.page.locator(".toasts")).toContainText("Document shared");
  await expect(lena.page.locator(".card", { hasText: "Shared documents" }).getByText("Passport (synthetic)")).toBeVisible({ timeout: 10_000 });
  await expect(rina.page.getByText("A document was shared that you are not authorised to open.")).toBeVisible({ timeout: 10_000 });

  // Remove the connected interpreter: their client is disconnected and the server shows no unauthorised presence.
  await maya.page.locator(".list > li", { hasText: "Rina Adler" }).getByRole("button", { name: "Remove" }).click();
  await maya.page.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  await expect(rina.page.getByText("The host removed you from the meeting.").first()).toBeVisible({ timeout: 15_000 });
  await expect(rina.page.locator(".video-grid")).toHaveCount(0);
  await expect.poll(async () => (await api(maya.page, "GET", `/api/meetings/${mid}/room-check`)).body?.connected?.length, { timeout: 20_000 }).toBe(2);
  const check = (await api(maya.page, "GET", `/api/meetings/${mid}/room-check`)).body;
  expect(check.unauthorized_connected).toEqual([]);
  await expect(maya.page.locator(".video-grid .tile")).toHaveCount(2, { timeout: 15_000 });
  expect((await api(rina.page, "POST", `/api/meetings/${mid}/token`)).status).toBe(403);

  // Host ends the meeting for everyone.
  await maya.page.getByRole("button", { name: "End meeting" }).click();
  await maya.page.getByRole("dialog").getByRole("button", { name: "End meeting" }).click();
  await expect(lena.page.getByText(/The host ended the meeting|This meeting has ended/).first()).toBeVisible({ timeout: 15_000 });
  await expect(lena.page.locator(".video-grid")).toHaveCount(0);

  for (const u of [maya, lena, rina]) expect(u.problems.filter((p) => !/DataChannel error on|data channel .* closed unexpectedly/.test(p))).toEqual([]);
  await Promise.all([maya.close(), lena.close(), rina.close()]);
});
