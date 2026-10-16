import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import path from "node:path";
import { accounts, authFile, login, REPO, watch } from "./helpers";

// User journeys through the real UI against the running stack. Each journey creates its own records
// (a new case, report or delegation), so the seeded demo scenario is extended, not changed.

async function as(browser: Browser, key: string): Promise<{ page: Page; problems: string[]; close: () => Promise<void> }> {
  const ctx = await browser.newContext({ storageState: authFile(key) });
  const page = await ctx.newPage();
  return { page, problems: watch(page), close: () => ctx.close() };
}
const dialog = (p: Page) => p.getByRole("dialog");
async function selectMatching(select: Locator, re: RegExp) {
  await expect(select.locator("option").filter({ hasText: re })).not.toHaveCount(0);
  const label = (await select.locator("option").allTextContents()).find((o) => re.test(o));
  if (!label) throw new Error(`no option matching ${re}`);
  await select.selectOption({ label });
}
const toast = (p: Page, text: string | RegExp) => expect(p.locator(".toasts")).toContainText(text);

test("A + C: relocation request → information request → four-eyes decision → appeal", async ({ browser }) => {
  test.setTimeout(180_000);
  const maya = await as(browser, "maya");
  // Start a new relocation journey.
  await maya.page.goto("/journeys");
  await maya.page.locator(".card", { hasText: "Relocate from Israel to Berlin, Germany" }).getByRole("button", { name: "Start a journey" }).click();
  await dialog(maya.page).getByRole("button", { name: /Create case with \d+ tasks/ }).click();
  await maya.page.waitForURL(/\/cases\/[0-9a-f-]+$/);
  const caseUrl = maya.page.url();
  await expect(maya.page.locator(".task").filter({ has: maya.page.getByText("Register your Berlin address", { exact: true }) })).toBeVisible();
  // Prepare and submit the Berlin address registration.
  await maya.page.locator(".task").filter({ has: maya.page.getByText("Register your Berlin address", { exact: true }) }).getByRole("button", { name: "Prepare request" }).click();
  await toast(maya.page, "Draft request prepared");
  await maya.page.getByRole("tab", { name: /Requests/ }).click();
  await maya.page.getByRole("button", { name: "Submit" }).click();
  await toast(maya.page, "Request submitted");
  const ref = (await maya.page.locator("main").innerText()).match(/SR-\d{4}-\d{6}/)![0];

  // Case officer: accept, assign, review, ask for information.
  const lena = await as(browser, "lena");
  await lena.page.goto("/authority/queue");
  await lena.page.getByLabel("Search").fill(ref);
  await lena.page.getByRole("link", { name: ref }).click();
  await lena.page.getByRole("button", { name: "Accept for triage" }).click();
  await toast(lena.page, "Request accepted");
  await lena.page.getByRole("button", { name: "Assign", exact: true }).click();
  await dialog(lena.page).getByRole("button", { name: "Assign" }).click();
  await lena.page.getByRole("button", { name: "Start review" }).click();
  await toast(lena.page, "Review started");
  await lena.page.getByRole("button", { name: "Request information" }).click();
  await dialog(lena.page).getByLabel("What do you need?").fill("Please confirm your move-in date in writing.");
  await dialog(lena.page).getByRole("button", { name: "Request information" }).click();
  await toast(lena.page, "SLA clock is paused");
  await expect(lena.page.getByText("Paused", { exact: true }).first()).toBeVisible();

  // Resident answers.
  await maya.page.goto(caseUrl);
  await maya.page.getByRole("tab", { name: /Requests/ }).click();
  await maya.page.getByLabel("Your response").fill("I move in on the first of next month.");
  await maya.page.getByRole("button", { name: "Send response" }).click();
  await toast(maya.page, "Response sent");

  // Officer proposes; the officer cannot approve their own decision.
  await lena.page.reload();
  await lena.page.getByRole("button", { name: "Propose decision" }).click();
  await dialog(lena.page).getByLabel("Rationale").fill("Rule DE-BER-ANMELDUNG v1: address and landlord confirmation provided; registration approved.");
  await dialog(lena.page).getByRole("button", { name: "Propose decision" }).click();
  await toast(lena.page, "A different supervisor must approve");
  await expect(lena.page.getByRole("button", { name: "Approve decision" })).toHaveCount(0);

  // Supervisor approves (four eyes).
  const thomas = await as(browser, "thomas");
  await thomas.page.goto(lena.page.url());
  await thomas.page.getByRole("button", { name: "Approve decision" }).click();
  await toast(thomas.page, "Decision approved and issued");

  // Resident sees the decision and appeals.
  await maya.page.reload();
  await maya.page.getByRole("tab", { name: /Requests/ }).click();
  await expect(maya.page.getByText("Version 1: Approved")).toBeVisible();
  await maya.page.getByRole("button", { name: "Appeal" }).click();
  await dialog(maya.page).getByLabel("Grounds for appeal").fill("The decision should also cover my child's registration.");
  await dialog(maya.page).getByRole("button", { name: "File appeal" }).click();
  await toast(maya.page, "Appeal filed");

  // The appeal reaches the authority queue as a linked follow-up request.
  await lena.page.goto("/authority/queue?kind=appeal");
  await expect(lena.page.locator("tbody tr").first()).toContainText("Appeal");

  for (const u of [maya, lena, thomas]) expect(u.problems).toEqual([]);
  await Promise.all([maya.close(), lena.close(), thomas.close()]);
});

test("B: incident report → triage → resolution → resident closes with rating", async ({ browser }) => {
  test.setTimeout(120_000);
  const maya = await as(browser, "maya");
  await maya.page.goto("/incidents?new=1");
  await selectMatching(dialog(maya.page).getByLabel("Municipality"), /Tel Aviv/);
  await dialog(maya.page).getByLabel("What is the problem?").fill("Streetlight is broken and flickering at the corner near the bus stop.");
  await dialog(maya.page).getByLabel("Street or landmark").fill("Bus stop, E2E test street");
  await dialog(maya.page).getByRole("button", { name: "Send report" }).click();
  await toast(maya.page, /Report INC-\d{4}-\d+ sent/);
  const ref = (await maya.page.locator(".toasts").innerText()).match(/INC-\d{4}-\d+/)![0];

  const amir = await as(browser, "amir");
  await amir.page.goto("/authority/incidents");
  await amir.page.getByLabel("Search").fill(ref);
  await amir.page.getByRole("link", { name: ref }).click();
  await amir.page.getByRole("button", { name: "Triage", exact: true }).click();
  await toast(amir.page, "Triaged");
  await amir.page.getByRole("button", { name: "Assign", exact: true }).click();
  await toast(amir.page, "Assigned");
  await amir.page.getByRole("button", { name: "Start work" }).click();
  await toast(amir.page, "Work started");
  await amir.page.getByRole("button", { name: "Mark resolved" }).click();
  await dialog(amir.page).getByLabel("What was done").fill("Replaced the lamp and the photocell.");
  await dialog(amir.page).getByRole("button", { name: "Mark resolved" }).click();
  await toast(amir.page, "Marked resolved");

  await maya.page.goto("/incidents");
  await maya.page.getByRole("link", { name: ref }).click();
  await expect(maya.page.getByText("Replaced the lamp and the photocell.")).toBeVisible();
  await expect(maya.page.locator("main")).not.toContainText("Amir");
  if (process.env.CB_SCREENSHOTS) await maya.page.screenshot({ path: path.join(REPO, "docs", "screenshots", "20-incident-resolved-citizen-view.png"), fullPage: true });
  await maya.page.getByRole("button", { name: "Confirm it is fixed" }).click();
  await dialog(maya.page).getByRole("radio", { name: "4 of 5" }).click();
  await dialog(maya.page).getByRole("button", { name: "Close report" }).click();
  await toast(maya.page, "Closed");
  for (const u of [maya, amir]) expect(u.problems).toEqual([]);
  await Promise.all([maya.close(), amir.close()]);
});

test("D: delegation is limited to its case and ends on revocation", async ({ browser }) => {
  const maya = await as(browser, "maya");
  await maya.page.goto("/cases");
  const firstCase = maya.page.locator("tbody tr").first();
  const caseRef = (await firstCase.locator("td").first().innerText()).trim();
  const caseHref = (await firstCase.getByRole("link").getAttribute("href"))!;
  await maya.page.goto("/delegations");
  await maya.page.getByRole("button", { name: "New delegation" }).click();
  const d = dialog(maya.page);
  await d.getByLabel("Professional").selectOption({ index: 1 });
  await selectMatching(d.getByLabel("Case", { exact: true }), new RegExp(`^${caseRef}`));
  await d.getByLabel("Purpose").fill("E2E: advice on this case only");
  await d.getByRole("button", { name: "Delegate" }).click();
  await toast(maya.page, "Delegation created");

  const david = await as(browser, "david");
  await david.page.goto(caseHref);
  await expect(david.page.locator("h1")).toBeVisible();
  await expect(david.page.getByText("You see this case through a delegation")).toBeVisible();

  // Revoke the delegation just created (newest first).
  await maya.page.reload();
  const row = maya.page.locator(".list > li", { hasText: "E2E: advice on this case only" }).first();
  await row.getByRole("button", { name: "Revoke" }).click();
  await dialog(maya.page).getByRole("button", { name: "Revoke" }).click();
  await toast(maya.page, "Delegation revoked");
  await david.page.reload();
  await expect(david.page.getByText("Not found, or you do not have access to it.")).toBeVisible();
  await Promise.all([maya.close(), david.close()]);
});

test("G: another authority cannot open a request outside its tenant", async ({ browser }) => {
  const lena = await as(browser, "lena");
  await lena.page.goto("/authority/queue");
  await lena.page.locator("tbody a.mono").first().click();
  const url = lena.page.url();
  const amir = await as(browser, "amir");
  await amir.page.goto(url);
  await expect(amir.page.getByText("Not found, or you do not have access to it.")).toBeVisible();
  const status = await amir.page.evaluate(async (u) => (await fetch(u.replace("/authority/requests/", "/api/authority/requests/"))).status, url);
  expect(status).toBe(404);
  await Promise.all([lena.close(), amir.close()]);
});

test("H: read-only account sees disabled controls and the server refuses changes", async ({ browser }) => {
  const viewer = await as(browser, "viewer");
  await viewer.page.goto("/wallet");
  await expect(viewer.page.getByText("Read-only demo account")).toBeVisible();
  const upload = viewer.page.getByRole("button", { name: "Upload document" });
  await expect(upload).toBeDisabled();
  await expect(upload).toHaveAttribute("title", "Not available for the read-only demo account");
  const res = await viewer.page.evaluate(async () => {
    const me = await (await fetch("/api/auth/me")).json();
    const r = await fetch("/api/cases", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token }, body: JSON.stringify({ title: "should fail" }) });
    return { status: r.status, body: await r.json() };
  });
  expect(res.status).toBe(403);
  expect(res.body.error.code).toBe("read_only_account");
  await viewer.close();
});

test("E: offline incident report is queued and replayed when back online", async ({ browser }) => {
  const maya = await as(browser, "maya");
  await maya.page.goto("/incidents");
  await expect(maya.page.locator("h1")).toBeVisible();
  await maya.page.waitForFunction(() => Object.keys(localStorage).some((k) => k.endsWith(".municipalities")));
  await maya.page.context().setOffline(true);
  await maya.page.getByRole("button", { name: "Report an issue" }).first().click();
  await expect(dialog(maya.page).getByText("You are offline")).toBeVisible();
  await dialog(maya.page).getByLabel("What is the problem?").fill("Overflowing waste bins next to the playground (offline E2E).");
  await dialog(maya.page).getByRole("button", { name: "Queue report" }).click();
  await toast(maya.page, "Report queued");
  await expect(maya.page.locator(".offline-pill")).toContainText("Offline");
  await maya.page.context().setOffline(false);
  await toast(maya.page, /queued item\(s\) sent/);
  await maya.page.goto("/incidents");
  await expect(maya.page.locator("tbody tr").first()).toContainText("Waste");
  await maya.close();
});

test("J: Rights Navigator answers with citations or abstains", async ({ browser }) => {
  const maya = await as(browser, "maya");
  await maya.page.goto("/rights");
  await maya.page.getByRole("tab", { name: "Ask a question" }).click();
  await maya.page.getByLabel("Your question").fill("How do I register my address in Berlin?");
  await maya.page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(maya.page.getByRole("heading", { name: /^(Answer|No supported answer)$/ })).toBeVisible();
  await expect(maya.page.getByText("Mode:")).toBeVisible();
  await maya.page.getByLabel("Your question").fill("What is the airspeed velocity of an unladen swallow?");
  await maya.page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(maya.page.getByRole("heading", { name: "No supported answer" })).toBeVisible();
  expect(maya.problems).toEqual([]);
  await maya.close();
});

test("K: governance verifies the audit chain and sees no case content", async ({ browser }) => {
  const gov = await as(browser, "auditor");
  await gov.page.goto("/governance/audit");
  await gov.page.getByRole("button", { name: "Verify chain" }).click();
  await expect(gov.page.getByText("Chain intact")).toBeVisible();
  const status = await gov.page.evaluate(async () => (await fetch("/api/cases")).status);
  expect([200, 403, 404]).toContain(status);
  if (status === 200) {
    const body = await gov.page.evaluate(async () => (await fetch("/api/cases")).json());
    expect(body.items).toEqual([]);
  }
  // Auditors can read but not change policies.
  await gov.page.goto("/governance/policies");
  await expect(gov.page.getByText("Changes need the governance administrator role")).toBeVisible();
  await gov.close();
});

test("I: wrong password is rejected; Hebrew switches the page to right-to-left", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(accounts().jonas.email);
  await page.getByLabel("Password", { exact: true }).fill("definitely-wrong-Password1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Email or password is incorrect.")).toBeVisible();
  await page.evaluate(() => localStorage.setItem("cb.locale", "he"));
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "he");
});

test("I: role switching changes the active tenant and is reversible", async ({ browser }) => {
  const lena = await as(browser, "lena");
  await lena.page.goto("/authority");
  const label = lena.page.locator(".ws-label");
  await expect(label).toContainText("Residents' Registration Office");
  const switchTo = async (name: RegExp) => {
    await lena.page.getByRole("button", { name: "Switch role" }).click();
    await lena.page.getByRole("menuitemradio", { name }).click();
  };
  await switchTo(/Berlin District Office/);
  await expect(label).toContainText("Berlin District Office");
  // Switch back so the saved session keeps its original context for other tests.
  await switchTo(/Residents' Registration Office/);
  await expect(label).toContainText("Residents' Registration Office");
  await lena.close();
});

test("E + I: sign-out warns about unsent items and removes them from the device", async ({ page }) => {
  await login(page, "jonas");
  const uid = await page.evaluate(async () => (await (await fetch("/api/auth/me")).json()).user.id);
  await page.goto("/incidents");
  await page.waitForFunction(() => Object.keys(localStorage).some((k) => k.endsWith(".municipalities")));
  // Keep replay failing so the item stays unsent after reconnecting.
  await page.route("**/api/sync/replay", (r) => r.abort());
  await page.context().setOffline(true);
  await page.getByRole("button", { name: "Report an issue" }).first().click();
  await page.getByRole("dialog").getByLabel("What is the problem?").fill("Unsent report that must be purged on sign-out.");
  await page.getByRole("dialog").getByRole("button", { name: "Queue report" }).click();
  await page.context().setOffline(false);
  await expect(page.locator(".offline-pill")).toContainText("waiting to sync");
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByRole("dialog")).toContainText("have not been sent yet");
  await page.getByRole("dialog").getByRole("button", { name: "Sign out and discard" }).click();
  await page.waitForURL("**/login");
  const left = await page.evaluate((id) => Object.keys(localStorage).filter((k) => k.includes(id)), uid);
  expect(left).toEqual([]);
  // The old session no longer works.
  expect(await page.evaluate(async () => (await fetch("/api/auth/me")).status)).toBe(401);
});

test("keyboard: skip link, tab keys and modal focus", async ({ browser }) => {
  const maya = await as(browser, "maya");
  await maya.page.goto("/consent");
  await expect(maya.page.locator("h1")).toBeVisible();
  await maya.page.keyboard.press("Tab");
  await expect(maya.page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await maya.page.keyboard.press("Enter");
  await expect(maya.page.locator("#main")).toBeFocused();
  const tab = maya.page.getByRole("tab").first();
  await tab.focus();
  await maya.page.keyboard.press("ArrowRight");
  await expect(maya.page.getByRole("tab").nth(1)).toBeFocused();
  await expect(maya.page.getByRole("tab").nth(1)).toHaveAttribute("aria-selected", "true");
  await maya.page.getByRole("button", { name: "Grant consent" }).first().click();
  await expect(maya.page.getByRole("dialog")).toBeVisible();
  await maya.page.keyboard.press("Escape");
  await expect(maya.page.getByRole("dialog")).toHaveCount(0);
  await expect(maya.page.getByRole("button", { name: "Grant consent" }).first()).toBeFocused();
  await maya.close();
});

test("Translator: mock mode translates only glossary phrases and marks the rest untranslated; review is human", async ({ browser }) => {
  const maya = await as(browser, "maya");
  await maya.page.goto("/translations");
  await maya.page.getByLabel("Text").fill("Hiermit bestätige ich den Einzug der folgenden Person.\n\nDer Hund frisst gern Äpfel im Garten.");
  await maya.page.getByRole("button", { name: "Translate" }).click();
  await maya.page.waitForURL(/\/translations\/[0-9a-f-]+$/);
  await expect(maya.page.getByText("I hereby confirm that the following person has moved in.").first()).toBeVisible();
  await expect(maya.page.getByText("Not translated").first()).toBeVisible();
  await expect(maya.page.getByText("Not certified", { exact: true })).toBeVisible();
  await maya.page.getByRole("button", { name: "Mark reviewed" }).click();
  await toast(maya.page, "Marked as reviewed");
  expect(maya.problems).toEqual([]);
  await maya.close();
});
