// The web fixes from batch A (#6–#9) and batches 081–083, driven in headless Chrome against a
// running api.
//
//   PUPPETEER_DIR=<dir with node_modules/puppeteer-core> node scripts/dev/web-smoke.mjs [base]
//
// base defaults to http://localhost:8000. Chrome comes from CHROME, default
// /usr/bin/google-chrome. Calls no model: nothing is asked. Leaves one throwaway account,
// smoke-<time>@example.com, for the caller to delete.

import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(`${process.env.PUPPETEER_DIR ?? process.cwd()}/`);
const puppeteer = require("puppeteer-core");

const base = process.argv[2] ?? "http://localhost:8000";
const chrome = process.env.CHROME ?? "/usr/bin/google-chrome";
const email = `smoke-${Date.now()}@example.com`;
// A code from the dev helper, since there is no mailbox to read it from.
const code = () =>
  execFileSync("uv", ["run", "python", "-m", "mycel.devtools.signin_code", email], {
    encoding: "utf8",
  }).trim();
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
};
const pause = (ms) => new Promise((done) => setTimeout(done, ms));

const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox"] });
const page = await browser.newPage();
const pageErrors = [];
// Counted from before the app loads: live scroll listeners and live ResizeObservers. The
// root's own scroll listener is React's event delegation, not the app's, so it is not counted.
await page.evaluateOnNewDocument(() => {
  window.__smoke = { scroll: 0, observers: 0 };
  const add = EventTarget.prototype.addEventListener;
  const remove = EventTarget.prototype.removeEventListener;
  EventTarget.prototype.addEventListener = function (type, ...rest) {
    if (type === "scroll" && this instanceof HTMLElement && this.id !== "root") window.__smoke.scroll += 1;
    return add.call(this, type, ...rest);
  };
  EventTarget.prototype.removeEventListener = function (type, ...rest) {
    if (type === "scroll" && this instanceof HTMLElement && this.id !== "root") window.__smoke.scroll -= 1;
    return remove.call(this, type, ...rest);
  };
  const Observer = window.ResizeObserver;
  window.ResizeObserver = class extends Observer {
    constructor(callback) {
      super(callback);
      window.__smoke.observers += 1;
    }
    disconnect() {
      window.__smoke.observers -= 1;
      super.disconnect();
    }
  };
});
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("dialog", (dialog) => void dialog.accept());

await page.goto(`${base}/app/home`, { waitUntil: "load" });
await page.evaluate(
  async (e, c) => {
    const body = JSON.stringify({ email: e, code: c });
    await fetch("/auth/code/verify", { method: "POST", headers: { "content-type": "application/json" }, body });
  },
  email,
  code(),
);

// #9 — the documents panel settles: no list stuck on "Loading…".
await page.goto(`${base}/app/`, { waitUntil: "load" });
await page.click('button[title="Your documents"]');
await page.waitForFunction(() => !document.querySelector(".kb-panel .empty")?.textContent?.includes("Loading"), { timeout: 10_000 });
check("#9 documents panel leaves Loading", true);

// #6 — upload, wait until ready, delete: no error, the row leaves.
const input = await page.$('.kb-panel input[type="file"]');
const file = "/tmp/web-smoke-note.md";
const { writeFileSync } = await import("node:fs");
writeFileSync(file, `# Smoke ${Date.now()}\n\nThe launch moved to Thursday.\n`);
await input.uploadFile(file);
await page.waitForSelector(".kb-list li", { timeout: 20_000 });
await page.waitForFunction(() => !document.querySelector(".kb-list li")?.textContent?.match(/queued|parsing|processing/i), { timeout: 60_000 });
const rowsBefore = await page.$$eval(".kb-list li", (rows) => rows.length);
await page.click('.kb-list li button[aria-label^="Delete"], .kb-list li button[title^="Delete"]');
await page.waitForFunction((n) => document.querySelectorAll(".kb-list li").length < n, { timeout: 20_000 }, rowsBefore);
const deleteError = await page.$eval(".kb-panel", (panel) => panel.querySelector(".kb-error")?.textContent ?? "");
check("#6 delete shows no error and the row leaves", deleteError === "", deleteError);

// #7 — re-rendering Ask does not pile up scroll listeners or observers.
await page.evaluate(() => {
  for (let i = 0; i < 30; i++) window.dispatchEvent(new Event("resize"));
});
await page.click('button[title="Your documents"]');
await page.click('button[title="Your documents"]');
await pause(500);
const live = await page.evaluate(() => window.__smoke);
check(
  "#7 Ask keeps one scroll listener and no stray observers",
  live.scroll <= 1 && live.observers <= 2 && pageErrors.length === 0,
  `scroll ${live.scroll}, observers ${live.observers}${pageErrors.length ? `; ${pageErrors.join("; ")}` : ""}`,
);

// 083 #60 — the same file twice is "Already uploaded", not a 500.
await input.uploadFile(file);
await page.waitForSelector(".kb-list li", { timeout: 20_000 });
await input.uploadFile(file);
await page.waitForFunction(() => document.querySelector(".kb-panel")?.textContent?.includes("Already uploaded"), { timeout: 10_000 }).catch(() => {});
const twice = await page.$eval(".kb-panel", (panel) => panel.textContent ?? "");
check("083 #60 the same file twice is refused as already uploaded", twice.includes("Already uploaded"), twice.slice(0, 120));
await page.click('.kb-list li button[aria-label^="Delete"], .kb-list li button[title^="Delete"]');
await pause(1000);

// 082 #52 — a 401 on a write (asking) drops the session, not only a 401 on a read.
await page.evaluate(() => fetch("/auth/logout", { method: "POST" }));
await page.type(".composer textarea", "still there?");
await page.keyboard.press("Enter");
await page.waitForFunction(() => /Sign in|Create an account/.test(document.body.innerText), { timeout: 10_000 }).catch(() => {});
const afterWrite = await page.evaluate(() => document.body.innerText);
check("082 #52 a 401 on a write leaves the app", /Sign in|Create an account/.test(afterWrite));

// 082 #51 — /auth/me failing shows a way to try again, not a blank page.
await page.setRequestInterception(true);
const refuseMe = (request) =>
  request.url().endsWith("/auth/me") ? request.respond({ status: 502, body: "bad gateway" }) : request.continue();
page.on("request", refuseMe);
await page.goto(`${base}/app/`, { waitUntil: "load" });
await page.waitForFunction(() => document.body.innerText.includes("Try again"), { timeout: 15_000 }).catch(() => {});
const unreachable = await page.evaluate(() => document.body.innerText);
check("082 #51 an unreachable api offers Try again", unreachable.includes("Try again"));
page.off("request", refuseMe);
await page.setRequestInterception(false);
await page.evaluate(
  async (e, c) => {
    const body = JSON.stringify({ email: e, code: c });
    await fetch("/auth/code/verify", { method: "POST", headers: { "content-type": "application/json" }, body });
  },
  email,
  code(),
);

// #9 — a killed session sends the reader to sign in rather than showing "no documents".
await page.evaluate(() => fetch("/auth/logout", { method: "POST" }));
await page.reload({ waitUntil: "load" });
await pause(1500);
const signedOut = await page.evaluate(() => document.body.innerText);
check("#9 a dead session leaves the app", /Sign in|Create an account/.test(signedOut));

check("#8 SourcePanel race (pinned in vitest; needs a cited answer, i.e. a model call)", true, "skipped in the browser");

await browser.close();
const failed = results.filter((ok) => !ok).length;
console.log(failed ? `${failed} failed` : "all passed", `· account ${email}`);
process.exit(failed ? 1 : 0);
