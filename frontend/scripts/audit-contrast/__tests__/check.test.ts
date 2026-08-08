/* THE CONTRAST AUDIT'S OWN VERDICT, CHECKED AGAINST LEDGERS WRITTEN TO BREAK EACH RULE.
 *
 * This repository has produced five measurement-tooling bugs, every one of them in code whose only job was
 * verifying something else, so the audit gets its own cases: a ledger with a control border below the floor, one
 * where the banned rule has drifted above it, one with a label that fails on a paper surface, and one whose
 * committed document has gone stale. Each is a hand-built ledger small enough to reason about by eye. */

import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { checkContrast } from "../check.ts";
import {
  buildLedger,
  contrastRatio,
  INDICATOR_FLOOR,
  TEXT_FLOOR,
  type Ledger,
  type Pair,
} from "../ledger.ts";
import { renderLedger } from "../render.ts";

const SURFACES = ["--paper", "--paper-raised"] as const;

function pair(ink: string, surface: string, ratio: number, floor: number): Pair {
  return {
    ink,
    surface,
    ratio,
    floor,
    floorFrom: `probe.css .x { color }`,
    clears: ratio >= floor,
  };
}

/** A ledger where every rule the audit states is satisfied. */
function healthy(overrides: readonly Pair[] = []): Ledger {
  const inks: Record<string, number> = {
    "--rule-control": 3.1,
    "--rule-strong": 2.65,
    "--ink": 10.6,
    "--ink-deep": 13.7,
    "--text-muted": 4.9,
  };
  const floors: Record<string, number> = {
    "--rule-control": INDICATOR_FLOOR,
    "--rule-strong": INDICATOR_FLOOR,
    "--ink": TEXT_FLOOR,
    "--ink-deep": TEXT_FLOOR,
    "--text-muted": TEXT_FLOOR,
  };
  const pairs = Object.entries(inks).flatMap(([ink, ratio]) =>
    SURFACES.map((surface) => pair(ink, surface, ratio, floors[ink])),
  );
  const replaced = pairs.filter(
    (one) => !overrides.some((over) => over.ink === one.ink && over.surface === one.surface),
  );
  return {
    inks: Object.keys(inks).toSorted(),
    surfaces: [...SURFACES],
    pairs: [...replaced, ...overrides],
    unmeasurable: [],
    sheets: ["probe.css"],
  };
}

/** The ledger written to a directory of its own, so the document check has something to compare against. */
async function committed(ledger: Ledger, text = renderLedger(ledger)): Promise<string> {
  const directory = await mkdtemp(path.join(tmpdir(), "syncr-contrast-"));
  const file = path.join(directory, "contrast-ledger.md");
  await writeFile(file, text, "utf8");
  return file;
}

async function checksOf(ledger: Ledger, text?: string): Promise<string[]> {
  const file = await committed(ledger, text);
  const outcome = await checkContrast({ ledger, ledgerFile: file });
  return outcome.findings.map((finding) => finding.check);
}

describe("the contrast audit", () => {
  it("passes a ledger where every rule it states is satisfied", async () => {
    expect(await checksOf(healthy())).toEqual([]);
  });

  it("refuses a control border that does not clear the indicator floor on a paper surface", async () => {
    const drifted = healthy([pair("--rule-control", "--paper", 2.9, INDICATOR_FLOOR)]);

    expect(await checksOf(drifted)).toEqual(["control-border-below-the-floor"]);
  });

  it("refuses a label that does not clear the text floor on a paper surface", async () => {
    const drifted = healthy([pair("--text-muted", "--paper-raised", 4.31, TEXT_FLOOR)]);

    expect(await checksOf(drifted)).toEqual(["text-below-the-floor"]);
  });

  /* The ban on `--rule-strong` for controls is a MEASUREMENT: it is banned because it is below the floor there, so
   * a retuned pigment that cleared it would make the ban itself the thing to revisit rather than something to keep
   * quietly. */
  it("reports the banned rule drifting ABOVE the floor, because then the ban needs revisiting", async () => {
    const retuned = healthy([pair("--rule-strong", "--paper", 3.2, INDICATOR_FLOOR)]);

    expect(await checksOf(retuned)).toEqual(["the-banned-rule-now-clears"]);
  });

  it("refuses a pair that has no ratio at all, which is a pair nobody has measured", async () => {
    const ledger = healthy();
    const missing: Ledger = {
      ...ledger,
      pairs: ledger.pairs.filter((one) => one.ink !== "--ink-deep"),
    };

    expect(await checksOf(missing)).toEqual(["text-below-the-floor", "text-below-the-floor"]);
  });

  it("refuses a committed document that is not what these tokens produce", async () => {
    const ledger = healthy();

    expect(await checksOf(ledger, "# Contrast ledger\n\nsomething else\n")).toEqual([
      "ledger-stale",
    ]);
  });
});

describe("the ratio itself", () => {
  /* The formula, against figures that are known independently of this code: WCAG's own bounds. */
  it("is 21 for black on white and 1 for a colour on itself", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#1a3aa6", "#1a3aa6")).toBeCloseTo(1, 10);
  });

  it("does not depend on which way round the pair is given", () => {
    expect(contrastRatio("#16307f", "#f6f2e7")).toBeCloseTo(
      contrastRatio("#f6f2e7", "#16307f"),
      10,
    );
  });
});

describe("the ledger the shipped stylesheets produce", () => {
  it("covers every ink against every surface, with no cell left without a ratio", async () => {
    const ledger = await buildLedger();

    expect(ledger.pairs).toHaveLength(ledger.inks.length * ledger.surfaces.length);
    for (const one of ledger.pairs) expect(Number.isFinite(one.ratio)).toBe(true);
  });

  it("reads the palette from the shipped sheets, so it is not measuring the token layer's declarations", async () => {
    const ledger = await buildLedger();

    /* Layer 0 is raw pigment ramps and every step there ends in a number. A ledger that had read the token layer
     * for USAGE would carry rows for ramp steps no component may reference. */
    expect(ledger.inks.filter((ink) => /-\d00$/.test(ink))).toEqual([]);
    expect(ledger.inks.length).toBeGreaterThan(15);
    expect(ledger.surfaces).toContain("--paper");
    expect(ledger.surfaces).toContain("--paper-raised");
  });

  /* The two figures the design language states in words, read out of the generated matrix rather than out of a
   * comment. Amber has no text step precisely because these two differ across the floor. */
  it("measures amber at 4.52 on raised paper and 4.18 on the page, which is why it has no text step", async () => {
    const ledger = await buildLedger();
    const on = (surface: string) =>
      ledger.pairs.find((one) => one.ink === "--signal-amber" && one.surface === surface)?.ratio ??
      0;

    expect(on("--paper-raised").toFixed(2)).toBe("4.52");
    expect(on("--paper").toFixed(2)).toBe("4.18");
  });
});
