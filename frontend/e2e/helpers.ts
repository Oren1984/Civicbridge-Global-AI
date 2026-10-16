import { execFileSync } from "node:child_process";
import { createHmac } from "node:crypto";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO = path.resolve(HERE, "..", "..");
export const authFile = (key: string) => path.join(HERE, ".auth", `${key}.json`);
export const hasAuth = (key: string) => existsSync(authFile(key));

interface Account { email: string; password: string; totp_secret?: string; read_only?: boolean }
let cache: Record<string, Account> | null = null;

/** Demo accounts generated on first start, read from the backend container (never from the repository). */
export function accounts(): Record<string, Account> {
  if (!cache) {
    const raw = execFileSync("docker", ["compose", "exec", "-T", "backend", "cat", "/run/civicbridge/demo/demo_credentials.json"], { cwd: REPO, encoding: "utf-8" });
    cache = JSON.parse(raw).accounts;
  }
  return cache!;
}

function base32(s: string): Buffer {
  const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of s.replace(/=+$/, "").toUpperCase()) bits += alpha.indexOf(c).toString(2).padStart(5, "0");
  const out: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}

function totpAt(secret: string, step: number): string {
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(step));
  const h = createHmac("sha1", base32(secret)).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

const usedStep: Record<string, number> = {};
/** A TOTP code for a step this run has not used yet (the server rejects replayed codes). */
export async function freshTotp(key: string): Promise<string> {
  const secret = accounts()[key].totp_secret!;
  for (;;) {
    const step = Math.floor(Date.now() / 30_000);
    if (usedStep[key] !== step) {
      usedStep[key] = step;
      return totpAt(secret, step);
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

export async function login(page: Page, key: string) {
  const a = accounts()[key];
  await page.goto("/login");
  await page.getByLabel("Email").fill(a.email);
  await page.getByLabel("Password", { exact: true }).fill(a.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  // After sign-in the UI switches to the account's own language, so the MFA step is matched by structure.
  if (a.totp_secret) {
    await page.waitForURL("**/mfa");
    await page.locator('input[autocomplete="one-time-code"]').fill(await freshTotp(key));
    await page.locator('form button[type="submit"]').click();
  }
  await expect(page.locator("#main")).toBeVisible();
  // Tests read English text: pin the stored interface language for the saved session.
  await page.evaluate(() => localStorage.setItem("cb.locale", "en"));
}

/** Collects uncaught errors, console errors and server errors while a test runs. */
export function watch(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource: the server responded with a status of (401|403|404|409|423)/.test(m.text())) problems.push(`console: ${m.text()}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.request().method()} ${r.url()}`);
  });
  return problems;
}
