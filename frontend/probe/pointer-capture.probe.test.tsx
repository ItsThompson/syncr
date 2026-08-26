/* THE EVENT ORDERING A DISCRETE DRAG'S CANCEL PATH RESTS ON, OBSERVED IN A REAL BROWSER OVER REAL POINTER INPUT.
 *
 * NOT A GATE, AND NOT IN THE SUITE, for the same reason the table's and the ledger row's probes are not: jsdom
 * dispatches neither `pointercancel` nor `lostpointercapture`, so the committed suite can hold the listeners and
 * the spec citation but never see either fire. The drag's cancel-on-capture-loss therefore rests on a READING of
 * the Pointer Events specification. This file turns that reading into a MEASUREMENT. It is run explicitly:
 *
 *   npx vitest run --config probe/vitest.config.ts probe/pointer-capture.probe.test.tsx
 *
 * WHAT IT SETTLES:
 *
 *   1. a real `setPointerCapture` delivers `gotpointercapture`, and an ordinary release delivers
 *      `lostpointercapture` AFTER `pointerup`, which is what makes capture loss a no-op on a real drop
 *      (the window `clear()` runs twice, and the second run finds nothing left to clear),
 *   2. a mid-drag `releasePointerCapture` delivers `lostpointercapture` with NO `pointerup` before it,
 *      which is the cancel path itself: the drag ends having stated nothing,
 *   3. and no `pointercancel` rides along with an ordinary release.
 *
 * Where the observed order differs from the expected one, every assertion here fails with a message that names
 * the order it saw, so a divergence is recorded rather than smoothed over.
 *
 * THE INPUT IS REAL, NOT SYNTHETIC. `dispatchEvent(new PointerEvent("pointerdown"))` does not make a pointer
 * active, and `setPointerCapture` throws NotFoundError without one, so a page that fakes its own events cannot
 * reach the behaviour this file measures. Chrome is driven over the DevTools protocol instead:
 * `Input.dispatchMouseEvent` enters at the browser's input pipeline, the same place a trackpad enters, and the
 * pointer becomes active in the only way there is.
 *
 * THE PAGE'S WIRING MIRRORS THE PRODUCT'S WITHOUT IMPORTING IT. The press handler calls `setPointerCapture`
 * exactly as `DayColumn`'s block handler does, and the window listeners are exactly the set
 * `useDiscreteDrag.ts` attaches (`pointerup` states a placement; `pointercancel` and `lostpointercapture`
 * cancel). Neither product file is imported or editable from here: the harness is a stand-in for the wiring,
 * because what is under measurement is the browser's ordering of the events both files listen for, not the
 * files themselves. If DayColumn ever stops capturing, mutation 3 in this ticket's verification record shows
 * what that costs: the cancel path silently ceases to exist.
 *
 * Nothing is written inside the repository: the page goes to a fresh temporary directory whose path is printed,
 * so a reader can open the exact document that was measured. */

import { spawn } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { BROWSER_ENV, findBrowser } from "../scripts/check-render/browser.ts";

/* The two pads sit at fixed coordinates so the DevTools mouse events land inside them without reading layout. */
const DROP_PAD_AT = { x: 100, y: 270 };
const RELEASE_PAD_AT = { x: 300, y: 270 };

const PAGE_SCRIPT = `
  const logs = { "pad-drop": [], "pad-release": [] };

  function padOf(event) {
    const pad = event.target instanceof Element ? event.target.closest(".pad") : null;
    return pad === null ? null : pad.id;
  }

  /* THE PRESS CAPTURES, as the product's block handler does. Every subsequent pointer event over this pointer is
   * retargeted to the pad, so the window listeners below tag each one with the pad it belongs to. */
  for (const pad of document.querySelectorAll(".pad")) {
    pad.addEventListener("pointerdown", (event) => {
      logs[pad.id].push("pointerdown");
      event.currentTarget.setPointerCapture(event.pointerId);
      pad.__pointerId = event.pointerId;
    });
  }
  for (const name of ["gotpointercapture", "pointermove", "pointerup", "pointercancel", "lostpointercapture"]) {
    window.addEventListener(name, (event) => {
      const padId = padOf(event);
      if (padId !== null) logs[padId].push(name);
    });
  }

  /* The capture-loss scenario: the pointer stays down and the page gives the capture up. */
  window.releasePadRelease = () => {
    const pad = document.getElementById("pad-release");
    pad.releasePointerCapture(pad.__pointerId);
  };
  window.readLogs = () => JSON.stringify(logs);
  window.clearLogs = () => { for (const id of Object.keys(logs)) logs[id] = []; };
`;

function pageHtml(): string {
  return [
    "<!doctype html>",
    '<html lang="en"><head><meta charset="utf-8"></head><body>',
    `<div class="pad" id="pad-drop" style="position:fixed;left:${String(DROP_PAD_AT.x - 60)}px;top:70px;width:120px;height:400px"></div>`,
    `<div class="pad" id="pad-release" style="position:fixed;left:${String(RELEASE_PAD_AT.x - 60)}px;top:70px;width:120px;height:400px"></div>`,
    '<pre id="readings"></pre>',
    `<script>${PAGE_SCRIPT}</script>`,
    "</body></html>",
  ].join("\n");
}

/* --- The DevTools connection ---------------------------------------------------------------------------------------*/

interface CdpConnection {
  call(method: string, params?: Record<string, unknown>): Promise<unknown>;
  close(): void;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Chrome with `--remote-debugging-port=0` writes the chosen port here once it is accepting connections. */
async function awaitDevtoolsPort(profileDir: string): Promise<number> {
  const file = path.join(profileDir, "DevToolsActivePort");
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      // oxlint-disable-next-line no-await-in-loop -- each check re-reads a file the last check found absent
      const [portLine] = (await readFile(file, "utf8")).split("\n");
      if (portLine !== undefined && portLine.trim() !== "") return Number(portLine.trim());
    } catch {
      /* not written yet */
    }
    // oxlint-disable-next-line no-await-in-loop -- the wait between checks is what bounds them
    await sleep(50);
  }
  throw new Error(`Chrome wrote no ${file}`);
}

async function connectCdp(browser: string, run: string): Promise<CdpConnection> {
  const profileDir = path.join(run, "chrome-profile");
  const child = spawn(
    browser,
    [
      "--headless=new",
      `--user-data-dir=${profileDir}`,
      "--remote-debugging-port=0",
      "--no-first-run",
      "--disable-gpu",
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "ignore"] },
  );
  const port = await awaitDevtoolsPort(profileDir);
  const targets = (await (await fetch(`http://127.0.0.1:${String(port)}/json/list`)).json()) as {
    type: string;
    webSocketDebuggerUrl?: string;
  }[];
  const target = targets.find(
    (each) => each.type === "page" && each.webSocketDebuggerUrl !== undefined,
  );
  if (target === undefined) throw new Error("Chrome exposed no page target");

  const ws = new WebSocket(target.webSocketDebuggerUrl as string);
  await new Promise<void>((resolve, reject) => {
    ws.addEventListener("open", () => resolve(), { once: true });
    ws.addEventListener("error", () => reject(new Error("the DevTools websocket refused")), {
      once: true,
    });
  });

  let nextId = 0;
  const pending = new Map<
    number,
    { resolve: (value: unknown) => void; reject: (error: Error) => void }
  >();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(String(event.data)) as {
      id?: number;
      error?: { message: string };
      result?: unknown;
    };
    if (message.id === undefined || !pending.has(message.id)) return;
    const settle = pending.get(message.id);
    pending.delete(message.id);
    if (settle === undefined) return;
    if (message.error !== undefined) settle.reject(new Error(message.error.message));
    else settle.resolve(message.result);
  });

  return {
    call(method, params) {
      const id = ++nextId;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify(params === undefined ? { id, method } : { id, method, params }));
      });
    },
    close() {
      ws.close();
      child.kill();
    },
  };
}

/** Every assertion failure carries the order the page saw, so a divergence names itself rather than smoothing over. */
function finding(order: readonly LogName[]): string {
  return `observed order: ${order.join(" -> ")}`;
}

async function evaluateString(connection: CdpConnection, expression: string): Promise<string> {
  const result = (await connection.call("Runtime.evaluate", {
    expression,
    returnByValue: true,
  })) as { result: { value?: unknown } };
  return String(result.result.value ?? "");
}

/* --- Driving the scenarios over real input -----------------------------------------*/

type LogName =
  | "gotpointercapture"
  | "pointermove"
  | "pointerup"
  | "pointercancel"
  | "lostpointercapture"
  | "pointerdown";

interface Logs {
  readonly [padId: string]: readonly LogName[];
}

async function readLogs(connection: CdpConnection): Promise<Logs> {
  return JSON.parse(await evaluateString(connection, "window.readLogs()")) as Logs;
}

/** Waits until the page's own script is live: input sent earlier lands on a document with no listeners yet. */
async function awaitPageReady(connection: CdpConnection): Promise<void> {
  const deadline = Date.now() + 10_000;
  for (;;) {
    // oxlint-disable-next-line no-await-in-loop -- each poll runs only after the previous one has answered
    const ready = await evaluateString(
      connection,
      "typeof window.readLogs === 'function' ? '1' : '0'",
    );
    if (ready === "1") return;
    if (Date.now() > deadline) throw new Error("the page never became ready");
    // oxlint-disable-next-line no-await-in-loop -- the wait between polls is what bounds them
    await sleep(25);
  }
}

/** Waits until the named event has landed in the pad's log, since input delivery is asynchronous to this call. */
async function awaitEvent(connection: CdpConnection, padId: string, name: LogName): Promise<Logs> {
  const deadline = Date.now() + 5_000;
  for (;;) {
    // oxlint-disable-next-line no-await-in-loop -- each poll reads the log the previous poll left behind
    const logs = await readLogs(connection);
    if (logs[padId]?.includes(name)) return logs;
    if (Date.now() > deadline)
      throw new Error(`${name} never arrived at ${padId}; logs: ${JSON.stringify(logs)}`);
    // oxlint-disable-next-line no-await-in-loop -- the wait between polls is what bounds them
    await sleep(25);
  }
}

async function dispatchMouse(
  connection: CdpConnection,
  type: "mousePressed" | "mouseMoved" | "mouseReleased",
  x: number,
  y: number,
  buttons: number,
): Promise<void> {
  await connection.call("Input.dispatchMouseEvent", {
    type,
    x,
    y,
    button: "left",
    buttons,
    clickCount: 1,
    pointerType: "mouse",
  });
}

describe("the pointer-capture event ordering a discrete drag rests on", () => {
  let connection: CdpConnection | undefined;
  let dropLog: readonly LogName[] = [];
  let releasedLog: readonly LogName[] = [];

  beforeAll(async () => {
    const browser = await findBrowser();
    if (browser === null) throw new Error(`no Chrome found. Point ${BROWSER_ENV} at one`);

    const run = await mkdtemp(path.join(tmpdir(), "syncr-capture-probe-"));
    const page = path.join(run, "page.html");
    await writeFile(page, pageHtml(), "utf8");
    process.stdout.write(`the page is in ${run}\n`);

    connection = await connectCdp(browser, run);
    await connection.call("Page.navigate", { url: `file://${page}` });
    await awaitPageReady(connection);

    /* Scenario 1: press, travel, and release. An ordinary drag that states a placement. The two-pixel nudge
     * after the press exists because the specification has pending capture processed immediately before the
     * next pointer event fires: with no further input, `gotpointercapture` itself never gets delivered. */
    await dispatchMouse(connection, "mousePressed", DROP_PAD_AT.x, DROP_PAD_AT.y, 1);
    await dispatchMouse(connection, "mouseMoved", DROP_PAD_AT.x + 2, DROP_PAD_AT.y, 1);
    await awaitEvent(connection, "pad-drop", "gotpointercapture");
    await dispatchMouse(connection, "mouseMoved", DROP_PAD_AT.x + 10, DROP_PAD_AT.y - 90, 1);
    await dispatchMouse(connection, "mouseReleased", DROP_PAD_AT.x + 20, DROP_PAD_AT.y - 120, 0);
    dropLog = (await awaitEvent(connection, "pad-drop", "lostpointercapture"))["pad-drop"] ?? [];

    await evaluateString(connection, "window.clearLogs()");

    /* Scenario 2: press, then the page gives the capture up while the button is still held. The same nudge
     * first delivers `gotpointercapture`, so the loss observed afterwards is unambiguously a LOSS and not a
     * capture that never completed. */
    await dispatchMouse(connection, "mousePressed", RELEASE_PAD_AT.x, RELEASE_PAD_AT.y, 1);
    await dispatchMouse(connection, "mouseMoved", RELEASE_PAD_AT.x + 2, RELEASE_PAD_AT.y, 1);
    await awaitEvent(connection, "pad-release", "gotpointercapture");
    await evaluateString(connection, "window.releasePadRelease()");
    await dispatchMouse(connection, "mouseMoved", RELEASE_PAD_AT.x + 4, RELEASE_PAD_AT.y, 1);
    releasedLog =
      (await awaitEvent(connection, "pad-release", "lostpointercapture"))["pad-release"] ?? [];

    process.stdout.write(`ordinary release observed: ${dropLog.join(" -> ")}\n`);
    process.stdout.write(`mid-drag capture loss observed: ${releasedLog.join(" -> ")}\n`);
  }, 30_000);

  afterAll(() => {
    connection?.close();
  });

  // oxlint-disable vitest/valid-expect -- every failure message carries the order the page saw, which is what
  // turns a divergence into a named finding rather than a bare false

  it("captures for real: gotpointercapture arrives on press", () => {
    expect(dropLog.includes("gotpointercapture"), finding(dropLog)).toBe(true);
  });

  it("delivers lostpointercapture AFTER pointerup on an ordinary release", () => {
    const upAt = dropLog.indexOf("pointerup");
    const lostAt = dropLog.indexOf("lostpointercapture");
    expect(upAt, finding(dropLog)).toBeGreaterThanOrEqual(0);
    expect(lostAt, finding(dropLog)).toBeGreaterThan(upAt);
  });

  it("rides no pointercancel on an ordinary release", () => {
    expect(dropLog.includes("pointercancel"), finding(dropLog)).toBe(false);
  });

  it("delivers lostpointercapture with NO pointerup when capture is given up mid-drag", () => {
    expect(releasedLog.includes("pointerup"), finding(releasedLog)).toBe(false);
    const downAt = releasedLog.indexOf("pointerdown");
    const lostAt = releasedLog.indexOf("lostpointercapture");
    expect(downAt, finding(releasedLog)).toBeGreaterThanOrEqual(0);
    expect(lostAt, finding(releasedLog)).toBeGreaterThan(downAt);
  });

  // oxlint-enable vitest/valid-expect
});
