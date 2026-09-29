// Record the 2-minute Rederive demo against a running stack.
//
//   REDERIVE_REBUILD_DELAY=0.6 python -m server.workers.rebuild   # one worker, slowed down
//   node demo/record_demo.mjs                                     # writes docs/demo.webm
//
// Needs the API on :8000 (with REDERIVE_ALLOW_RESET=1), the UI on :3000, and
// Playwright. Set CHROMIUM_PATH to use a specific browser binary.

import { execSync } from "node:child_process";
import { mkdirSync, renameSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const API = process.env.API_URL ?? "http://localhost:8000";
const UI = process.env.UI_URL ?? "http://localhost:3000";
const OUT = path.join(ROOT, "docs", "demo.webm");
const TMP = path.join(ROOT, "docs", ".video-tmp");

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require("playwright");
} catch {
  const globalRoot = execSync("npm root -g").toString().trim();
  playwright = require(path.join(globalRoot, "playwright"));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function caption(page, text) {
  await page.evaluate((t) => {
    let el = document.getElementById("demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-caption";
      Object.assign(el.style, {
        position: "fixed", left: "50%", bottom: "28px", transform: "translateX(-50%)",
        zIndex: 9999, maxWidth: "900px", padding: "12px 20px", borderRadius: "10px",
        background: "rgba(20,20,18,0.92)", color: "#fff", font: "600 18px/1.4 system-ui, sans-serif",
        textAlign: "center", boxShadow: "0 6px 24px rgba(0,0,0,0.25)", transition: "opacity 0.3s",
      });
      document.body.appendChild(el);
    }
    el.style.opacity = "0";
    setTimeout(() => { el.textContent = t; el.style.opacity = "1"; }, 250);
  }, text);
  await sleep(400);
}

// Draw a ring around an element before clicking it, since the video has no cursor.
async function highlight(locator) {
  const box = await locator.boundingBox();
  if (!box) return;
  await locator.page().evaluate((b) => {
    const ring = document.createElement("div");
    Object.assign(ring.style, {
      position: "fixed", left: `${b.x - 6}px`, top: `${b.y - 6}px`, width: `${b.width + 12}px`,
      height: `${b.height + 12}px`, border: "3px solid #e0a54a", borderRadius: "10px",
      zIndex: 9998, pointerEvents: "none", transition: "opacity 0.6s",
    });
    document.body.appendChild(ring);
    setTimeout(() => (ring.style.opacity = "0"), 1100);
    setTimeout(() => ring.remove(), 1800);
  }, box);
  await sleep(700);
}

async function click(locator) {
  await highlight(locator);
  await locator.click({ force: true });
}

const nodeNamed = (page, name) =>
  page.locator(".react-flow__node", { has: page.locator(".name span", { hasText: new RegExp(`^${name}$`) }) });

// Zoom the graph toward the center of the matching nodes with the mouse wheel.
async function zoomTo(page, selector) {
  const boxes = (await Promise.all((await page.locator(selector).all()).map((n) => n.boundingBox())))
    .filter(Boolean);
  if (!boxes.length) return;
  const x0 = Math.min(...boxes.map((b) => b.x)), x1 = Math.max(...boxes.map((b) => b.x + b.width));
  const y0 = Math.min(...boxes.map((b) => b.y)), y1 = Math.max(...boxes.map((b) => b.y + b.height));
  await page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2);
  for (let i = 0; i < 4; i++) {
    await page.mouse.wheel(0, -120);
    await sleep(120);
  }
  await sleep(500);
}

// Zoom out to the whole graph first so the node is on screen, then select it.
async function clickNode(page, name) {
  await page.locator(".react-flow__controls-fitview").click();
  await sleep(900);
  await click(nodeNamed(page, name));
}

async function main() {
  // Fresh data: 40 messages and 49 derived records.
  await fetch(`${API}/admin/reset`, { method: "POST" });
  execSync(`python3 -m demo_agent.support_agent --seed-only --no-reset --url ${API}`, {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: `${ROOT}/sdk:${ROOT}` },
    stdio: "inherit",
  });
  const graph = await (await fetch(`${API}/graph`)).json();
  const byName = Object.fromEntries(
    graph.nodes.filter((n) => !n.meta.partial).map((n) => [n.meta.name, n]),
  );

  rmSync(TMP, { recursive: true, force: true });
  mkdirSync(TMP, { recursive: true });
  const browser = await playwright.chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: TMP, size: { width: 1440, height: 900 } },
  });
  const page = await context.newPage();
  await page.goto(UI);
  await page.waitForSelector(".node");
  // The minimap sits under the captions. Hide it for the recording.
  await page.addStyleTag({ content: ".react-flow__minimap { display: none; }" });
  await sleep(1200);

  // 1. The memory graph.
  await caption(page, "An agent's memory: 40 chat messages (left) and 49 memories derived from them.");
  await sleep(6000);
  await caption(page, "Every summary, belief, and procedure records its exact inputs and the recipe that built it.");
  await sleep(6000);

  // 2. The profile says Globex.
  await clickNode(page, "profile");
  await caption(page, "The customer profile says Dana works at Globex.");
  await sleep(7000);

  // 3. A tool call uses it.
  for (const name of ["profile", "renewal_outreach"]) {
    await fetch(`${API}/records/${byName[name].id}?tool_call_id=draft_reply-0142&tool_name=draft_reply`);
  }
  await caption(page, "The agent's draft_reply tool reads it and plans: contact Priya at Globex before renewal.");
  await sleep(7000);

  // 4. The source message was wrong.
  await clickNode(page, "m_globex");
  await caption(page, "But this message was wrong. Dana was talking about a vendor, not her employer.");
  await sleep(6500);
  await caption(page, "Retract it.");
  await sleep(1500);
  await click(page.getByRole("button", { name: "Retract", exact: true }));
  await sleep(1500);
  await click(page.getByRole("alertdialog").getByRole("button", { name: "Retract" }));

  // 5. Watch the cascade, zoomed in on the records that went stale.
  await click(page.locator(".react-flow__controls-fitview"));
  await sleep(900);
  await zoomTo(page, ".react-flow__node:has(.node.stale), .react-flow__node:has(.node.rebuilding)");
  await caption(page, "14 descendants go stale (amber). Workers rebuild them in topological order (blue).");
  await sleep(9000);
  await caption(page, "Purple flashes are early cutoffs: the rebuilt text says the same thing, so the cascade stops there.");
  await sleep(8000);

  // 6. The tally.
  // A real LLM rebuilds slower than the fake provider. Wait for the queue to drain.
  let s;
  for (let i = 0; i < 240; i++) {
    s = (await (await fetch(`${API}/jobs`)).json()).summary;
    if (!s.queued && !s.running) break;
    await sleep(500);
  }
  await click(page.getByRole("tab", { name: /Events/ }));
  await caption(page, `${s.done ?? 0} rebuilt with new content, ${s.cut_off ?? 0} cut off as equivalent, ` +
    `${s.skipped ?? 0} skipped with no model call.`);
  await sleep(9000);

  // 7. The diff.
  await clickNode(page, "profile");
  await caption(page, "The profile is now version 2. The diff shows exactly what changed.");
  await sleep(4000);
  await page.locator(".diff").first().scrollIntoViewIfNeeded();
  await highlight(page.locator(".diff").first());
  await caption(page, "Globex is gone. Initech came from another message that was always there.");
  await sleep(8000);

  // 8. The exposure report.
  await click(page.getByRole("tab", { name: "Exposure" }));
  await caption(page, "The exposure report lists past tool calls that read memory that is now invalid.");
  await sleep(6000);
  await highlight(page.locator(".call").first());
  await caption(page, "draft_reply acted on the wrong employer. Now you know which actions to review.");
  await sleep(9000);

  // 9. Close.
  await click(page.locator(".react-flow__controls-fitview"));
  await caption(page, "Rederive: retract a memory, rebuild what depends on it, stop early, and audit what it touched.");
  await sleep(7000);

  const video = page.video();
  await context.close();
  await browser.close();
  const src = await video.path();
  renameSync(src, OUT);
  rmSync(TMP, { recursive: true, force: true });
  console.log(`saved ${path.relative(ROOT, OUT)}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
