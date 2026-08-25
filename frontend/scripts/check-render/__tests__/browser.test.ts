/* THE NO-BROWSER PATH, AND WHY IT IS A TEST AND NOT A HOPE.
 *
 * The gate's whole contract is that it REFUSES rather than skips when no browser is present: a check
 * that passes when it cannot look reports a claim it never tested. Running the CLI on a machine that
 * has Chrome exercises only the happy path, so the refusal is held here: with no browser to find,
 * `checkRender` must produce the no-browser finding naming SYNCR_CHROME as the fix, and
 * `reportOutcome` must turn that finding into exit code 1 -- a red gate, not a green claim.
 * `findBrowser` is stubbed at its own module boundary (the one seam this machine cannot reach, which
 * always has Chrome installed); everything else runs for real, and the operator-supplied path is
 * asserted against the real filesystem. */

import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/* Importing the mocked module also runs its factory below, which stashes the original `findBrowser`
 * before anything replaces it. BROWSER_ENV survives the mock unchanged. */
import { BROWSER_ENV } from "../browser.ts";

const { findBrowser, realFindBrowser } = vi.hoisted(() => ({
  findBrowser: vi.fn<() => Promise<string | null>>(),
  /* The original implementation, stashed when the factory swaps the stub in. */
  realFindBrowser: { current: undefined as undefined | (() => Promise<string | null>) },
}));

vi.mock(import("../browser.ts"), async (importOriginal) => {
  const actual = await importOriginal<typeof import("../browser.ts")>();
  realFindBrowser.current = actual.findBrowser;
  return { ...actual, findBrowser };
});

beforeEach(() => {
  findBrowser.mockResolvedValue(null);
});

afterEach(() => {
  delete process.env.SYNCR_CHROME;
  vi.restoreAllMocks();
});

describe("findBrowser", () => {
  it("uses the path SYNCR_CHROME names when it exists, ahead of any candidate", async () => {
    if (realFindBrowser.current === undefined) throw new Error("the original was never loaded");
    const named = await mkdtemp(path.join(tmpdir(), "syncr-browser-"));

    process.env.SYNCR_CHROME = named;

    /* A directory passes the same existence probe a browser binary does, which is exactly why the
     * probe is an `access` and nothing cleverer: whatever it names, the operator meant it. */
    await expect(realFindBrowser.current()).resolves.toBe(named);
  });
});

describe("the no-browser refusal", () => {
  it("is one finding naming the fix, not a pass", async () => {
    const stderr = vi.spyOn(process.stderr, "write").mockReturnValue(true);
    const { checkRender } = await import("../check.ts");

    const outcome = await checkRender({ bundleName: "assets/index.css", css: "" });

    expect(outcome.findings).toHaveLength(1);
    expect(outcome.findings[0]?.check).toBe("no-browser");
    expect(outcome.findings[0]?.message).toContain(BROWSER_ENV);
    /* And the finding reddens the gate rather than reporting a green check that never ran. */
    const { reportOutcome } = await import("../../lib/report.ts");
    expect(reportOutcome("rendered pixels", outcome)).toBe(1);
    expect(
      stderr.mock.calls.some(([chunk]) => String(chunk).includes("no headless Chromium")),
    ).toBe(true);
  });
});
