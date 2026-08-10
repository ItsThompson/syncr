/* THE CONTRAST AUDIT'S OWN VERDICT, CHECKED AGAINST LEDGERS WRITTEN TO BREAK EACH RULE.
 *
 * This repository has produced five measurement-tooling bugs, every one of them in code whose only job was
 * verifying something else, so the audit gets its own cases. Each is a hand-built ledger small enough to reason
 * about by eye, written to break exactly one of the rules `check.ts` states, so a rule that stopped being enforced
 * has a red of its own rather than disappearing quietly. */

import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { checkContrast } from "../check.ts";
import { deadExcuses, EXCUSED_TEXT_INKS } from "../excuses.ts";
import {
  buildLedger,
  contrastRatio,
  INDICATOR_FLOOR,
  INK_FILLED,
  ratioOf,
  TEXT_FLOOR,
  textOnAnInkFill,
  type Composed,
  type Ledger,
  type Pair,
} from "../ledger.ts";
import { renderLedger } from "../render.ts";
import { paletteInUse } from "../usage.ts";

const PAPER = ["--paper", "--paper-raised"] as const;

/* Both surface classes, because the audit asks a different question of each: every ink can land on paper, and only
 * a stated pairing lands on an ink fill. */
const SURFACES = [...PAPER, ...INK_FILLED] as const;

/** The ink a synthetic ink-filled header draws with, and the ratio at which it is legible there. */
const INVERSE = "--probe-inverse";

/** The one pairing the healthy ledger's sheets state: an inverse ink on the fill it exists for. */
const STATED: Composed = {
  where: "probe.css .header { color }",
  ink: INVERSE,
  surface: INK_FILLED[1],
  floor: TEXT_FLOOR,
};

/* Every ink the real check excuses from the text floor, so a synthetic ledger can carry them and the both-ways
 * staleness rule has something to describe. Imported rather than restated: a fourth excuse added to the check
 * appears in these ledgers by itself. */
const EXCUSED = [...EXCUSED_TEXT_INKS];

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
function healthy(
  overrides: readonly Pair[] = [],
  composed: readonly Composed[] = [STATED],
): Ledger {
  const inks: Record<string, number> = {
    "--rule-control": 3.1,
    "--rule-strong": 2.65,
    "--ink": 10.6,
    "--ink-deep": 13.7,
    "--text-muted": 4.9,
    [INVERSE]: 14.8,
    /* The excused inks, each at a ratio that WOULD fail, which is why each is excused. A synthetic ledger without
     * them would leave the excuses describing nothing, and the check refuses that too. */
    ...Object.fromEntries(EXCUSED.map((ink) => [ink, 1.2])),
  };
  const floors: Record<string, number> = {
    "--rule-control": INDICATOR_FLOOR,
    "--rule-strong": INDICATOR_FLOOR,
    "--ink": TEXT_FLOOR,
    "--ink-deep": TEXT_FLOOR,
    "--text-muted": TEXT_FLOOR,
    [INVERSE]: TEXT_FLOOR,
    ...Object.fromEntries(EXCUSED.map((ink) => [ink, TEXT_FLOOR])),
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
    composed,
  };
}

/** The ledger written to a directory of its own, so the document check has something to compare against. */
async function committed(ledger: Ledger, text = renderLedger(ledger)): Promise<string> {
  const directory = await mkdtemp(path.join(tmpdir(), "syncr-contrast-"));
  const file = path.join(directory, "contrast-ledger.md");
  await writeFile(file, text, "utf8");
  return file;
}

async function checksOf(
  ledger: Ledger,
  text?: string,
  excuses?: {
    readonly excusedOnPaper?: Readonly<Record<string, string>>;
    readonly excusedOnAnInkFill?: Readonly<Record<string, string>>;
  },
): Promise<string[]> {
  const file = await committed(ledger, text);
  const outcome = await checkContrast({ ledger, ledgerFile: file, ...excuses });
  return outcome.findings.map((finding) => finding.check);
}

/** The number a note leads with, so a printed figure can be crossed against the ledger it came from. */
function figureIn(notes: readonly string[], phrase: string): number {
  const note = notes.find((one) => one.includes(phrase));
  if (note === undefined) throw new Error(`no note mentions ${phrase}`);
  return Number.parseInt(note, 10);
}

/* THE EXPECTED FIGURES, DERIVED FROM THE LEDGER WITHOUT CALLING WHAT THE GATE CALLS.
 *
 * An assertion that restates the implementation's expression agrees with a wrong formula by construction. These
 * read `ledger.pairs` and `ledger.composed` directly, so a rule count used where a cell count belongs is visible
 * here even though both readings walk the same data. */
function textInksOf(ledger: Ledger): Set<string> {
  return new Set(ledger.pairs.filter((one) => one.floor === TEXT_FLOOR).map((one) => one.ink));
}

function inkFillCellsOf(ledger: Ledger): Set<string> {
  const fills = new Set<string>(INK_FILLED);
  return new Set(
    ledger.composed
      .filter((one) => one.floor === TEXT_FLOOR && fills.has(one.surface))
      .map((one) => `${one.ink} ${one.surface}`),
  );
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

  /* THE COVERAGE RULE ITSELF. The derived enforcement set is drawn from the pairs, so an ink whose row went
   * missing would take its own rule with it and pass by absence. The gate refuses the incomplete matrix rather
   * than the ink, which is the failure that can actually happen. */
  it("refuses a matrix with a pair missing, which is a pair nobody has measured", async () => {
    const ledger = healthy();
    const missing: Ledger = {
      ...ledger,
      pairs: ledger.pairs.filter((one) => one.ink !== "--ink-deep"),
    };

    expect(await checksOf(missing)).toContain("incomplete-matrix");
  });

  it("names the ink whose row is short, so a finding points at something", async () => {
    const ledger = healthy();
    const missing: Ledger = {
      ...ledger,
      pairs: ledger.pairs.filter(
        (one) => !(one.ink === "--ink" && one.surface === "--paper-raised"),
      ),
    };
    const file = await committed(missing);
    const outcome = await checkContrast({ ledger: missing, ledgerFile: file });

    /* The list, not merely a mention of the ink: a finding that named every ink would contain this one too
     * and would point at nothing. */
    expect(outcome.findings.find((one) => one.check === "incomplete-matrix")?.message).toMatch(
      /Short rows: --ink$/,
    );
  });

  it("refuses a ledger that has not been written yet, so a missing document is not a clean run", async () => {
    const ledger = healthy();
    const absent = path.join(tmpdir(), "syncr-contrast-absent", "contrast-ledger.md");
    const outcome = await checkContrast({ ledger, ledgerFile: absent });

    expect(outcome.findings.map((one) => one.check)).toEqual(["ledger-missing"]);
  });

  /* THE NOTES ARE DERIVED, AND THAT IS ASSERTED against a second reading rather than against a copy of the
   * expression that produces them. A figure crossed against its own formula agrees with a wrong formula, which is
   * how a rule count came to be printed where a cell count belonged. */
  it("prints figures computed from the ledger it read, so a count cannot drift from its own subject", async () => {
    const ledger = healthy();
    const { notes } = await checkContrast({ ledger, ledgerFile: await committed(ledger) });
    const cells = textInksOf(ledger).size * INK_FILLED.length;

    expect(figureIn(notes, "stated pairing(s) on")).toBe(
      ledger.composed.filter((one) => one.floor === TEXT_FLOOR).length,
    );
    expect(figureIn(notes, "recorded and not enforced")).toBe(cells - inkFillCellsOf(ledger).size);
    expect(figureIn(notes, "do not clear the ink's floor")).toBe(
      ledger.pairs.filter((one) => !one.clears).length,
    );
  });

  /* THE CASE THAT TELLS THE TWO UNITS APART. Three of the shipped tree's four ink-fill pairings are the same matrix
   * cell, so a fixture carrying one rule per cell cannot see a rule count subtracted from a cell count. This one
   * states one cell twice: the pairing count is 2 and the unenforced figure has to move by 1, not by 2. */
  it("counts a cell once when two rules state it, so a rule count is not a cell count", async () => {
    const twice: Composed[] = [STATED, { ...STATED, where: "probe.css .dialog__header { color }" }];
    const ledger = healthy([], twice);
    const { notes } = await checkContrast({ ledger, ledgerFile: await committed(ledger) });
    const cells = textInksOf(ledger).size * INK_FILLED.length;

    expect(inkFillCellsOf(ledger).size).toBe(1);
    expect(figureIn(notes, "stated pairing(s) on")).toBe(2);
    expect(figureIn(notes, "recorded and not enforced")).toBe(cells - 1);
  });

  /* THE ENFORCEMENT SET IS DERIVED, and this is the plant the review used to show a list of three could not hold
   * the criterion: a new ink written as text, failing on both paper surfaces, shipped green over 506 pairs. */
  it("enforces the text floor on an ink it was never told about", async () => {
    const ledger = healthy([
      pair("--planted-label-ink", "--paper", 2.45, TEXT_FLOOR),
      pair("--planted-label-ink", "--paper-raised", 2.65, TEXT_FLOOR),
    ]);
    const named: Ledger = { ...ledger, inks: [...ledger.inks, "--planted-label-ink"].toSorted() };

    expect(await checksOf(named)).toContain("text-below-the-floor");
  });

  it("holds every ink the ledger puts at the text floor, minus the declared excuses", async () => {
    const ledger = healthy();
    const atTextFloor = ledger.inks.filter(
      (ink) => ledger.pairs.find((one) => one.ink === ink)?.floor === TEXT_FLOOR,
    );

    /* The excuses are a subset of the text inks, which is what makes each one checkable: an excuse for an ink the
     * product does not write as text describes nothing, and the gate says so. */
    expect(EXCUSED_TEXT_INKS.every((ink) => atTextFloor.includes(ink))).toBe(true);
    expect(atTextFloor.length).toBeGreaterThan(EXCUSED_TEXT_INKS.length);
  });

  it("refuses an excuse for an ink no shipped declaration writes as text any more", async () => {
    const ledger = healthy();
    const withoutTheExcused: Ledger = {
      ...ledger,
      inks: ledger.inks.filter((ink) => ink !== EXCUSED_TEXT_INKS[0]),
      pairs: ledger.pairs.filter((one) => one.ink !== EXCUSED_TEXT_INKS[0]),
    };

    expect(await checksOf(withoutTheExcused)).toContain("a-dead-excuse");
  });

  it("refuses a committed document that is not what these tokens produce", async () => {
    const ledger = healthy();

    expect(await checksOf(ledger, "# Contrast ledger\n\nsomething else\n")).toEqual([
      "ledger-stale",
    ]);
  });
});

/* THE INK-FILLED SURFACES, where the question is not the same as on paper.
 *
 * Every ink can land on paper, so the whole column is enforced there. Nothing states which class sits on an ink
 * fill, so enforcing that column would report every text ink against it and mean nothing. What a sheet can prove
 * is a rule that names its own fill and its own ink, and that is the set these cases hold. */
describe("the text floor on an ink-filled surface", () => {
  it("refuses a stated pairing whose ink cannot be read on the fill the same rule names", async () => {
    const drifted = healthy([pair(INVERSE, INK_FILLED[1], 1.29, TEXT_FLOOR)]);

    expect(await checksOf(drifted)).toEqual(["text-below-the-floor-on-an-ink-fill"]);
  });

  it("names the rule that states the pairing, because that is what a reader has to open", async () => {
    const drifted = healthy([pair(INVERSE, INK_FILLED[1], 1.29, TEXT_FLOOR)]);
    const outcome = await checkContrast({
      ledger: drifted,
      ledgerFile: await committed(drifted),
    });

    expect(outcome.findings[0]?.message).toContain(STATED.where);
  });

  /* A stated pairing with no cell in the matrix is a pairing nobody has measured, and the finding says so in
   * those words rather than printing a ratio it does not have. */
  it("says a stated pairing measures nothing when the matrix carries no cell for it", async () => {
    const ledger = healthy();
    const withoutTheCell: Ledger = {
      ...ledger,
      pairs: ledger.pairs.filter((one) => !(one.ink === INVERSE && one.surface === STATED.surface)),
    };
    const outcome = await checkContrast({
      ledger: withoutTheCell,
      ledgerFile: await committed(withoutTheCell),
    });

    expect(
      outcome.findings.find((one) => one.check === "text-below-the-floor-on-an-ink-fill")?.message,
    ).toContain(`${INVERSE} measures nothing`);
  });

  /* THE BOUNDARY, ASSERTED RATHER THAN LEFT IMPLICIT. An ink that fails on an ink fill and that no rule puts
   * there is recorded in the ledger and not enforced. Enforcing it would report every text ink against both fills,
   * which is a finding list nobody can act on and the reason this gate keys on the stated pairing. */
  it("does not enforce a pairing no rule states, however badly it measures", async () => {
    const unreachable = healthy([pair("--ink-deep", INK_FILLED[0], 1.29, TEXT_FLOOR)]);

    expect(await checksOf(unreachable)).toEqual([]);
  });

  /* THE ANTI-VACUITY CASE. Every pairing the real sheets state on an ink fill draws `--on-ink`, and `--on-ink` is
   * excused from the text floor on paper. One shared excuse list would therefore skip every pairing this rule has
   * to check, leaving a green that measured nothing. */
  it("holds an ink the paper rule excuses, because a paper excuse is not an ink-fill excuse", async () => {
    const excusedOnPaper = EXCUSED_TEXT_INKS[0];
    const composed: Composed = {
      where: "probe.css .header { color }",
      ink: excusedOnPaper,
      surface: INK_FILLED[0],
      floor: TEXT_FLOOR,
    };

    expect(await checksOf(healthy([], [composed]))).toEqual([
      "text-below-the-floor-on-an-ink-fill",
    ]);
  });

  /* THE READING'S OWN CONTROL. The enforced set is derived, so a reader that stopped finding pairings would hold
   * nothing to the floor and pass whatever the tree did. That is the vacuous green a list of three inks once
   * shipped over 506 pairs, and it is refused here in the only direction it can be: by absence. */
  it("refuses a run that found no stated pairing on an ink fill at all", async () => {
    expect(await checksOf(healthy([], []))).toEqual(["no-ink-fill-composition-read"]);
  });

  it("holds an indicator's stated pairing to no text floor, because its property is not a label's", async () => {
    const border: Composed = {
      where: "probe.css .divider { border-top-color }",
      ink: "--rule-strong",
      surface: INK_FILLED[0],
      floor: INDICATOR_FLOOR,
    };

    expect(await checksOf(healthy([], [STATED, border]))).toEqual([]);
  });
});

/* THE STALENESS RULE, AND THE SKIP AN ENTRY PRODUCES, both reached through the gate.
 *
 * The ink-fill list is empty in the shipped tree, so neither path can be reached through the module's own record.
 * The gate takes both lists as input for exactly that reason: a finding whose loop body has never executed in any
 * run or test is decoration, whatever its message says. */
describe("an excuse on an ink-filled surface", () => {
  const SUB_FLOOR: Composed = { ...STATED, ink: "--probe-illegible" };

  /** A ledger where one rule states a pairing that cannot be read on the fill it names. */
  function stating(): Ledger {
    const ledger = healthy([], [SUB_FLOOR]);
    return {
      ...ledger,
      inks: [...ledger.inks, SUB_FLOOR.ink].toSorted(),
      pairs: [
        ...ledger.pairs,
        ...SURFACES.map((surface) => pair(SUB_FLOOR.ink, surface, 1.29, TEXT_FLOOR)),
      ],
    };
  }

  it("silences the pairing it names, which is what an excuse is for", async () => {
    const ledger = stating();

    expect(await checksOf(ledger)).toContain("text-below-the-floor-on-an-ink-fill");
    expect(
      await checksOf(ledger, undefined, {
        excusedOnAnInkFill: {
          [SUB_FLOOR.ink]: "a structural guard stronger than a ratio covers it",
        },
      }),
    ).not.toContain("text-below-the-floor-on-an-ink-fill");
  });

  it("is reported when no rule states it any more, so it cannot outlive its case", async () => {
    const checks = await checksOf(healthy(), undefined, {
      excusedOnAnInkFill: { "--gone": "a reason for a pairing no rule states" },
    });

    expect(checks).toEqual(["a-dead-ink-fill-excuse"]);
  });

  it("names the ink and repeats the reason, so a stale excuse can be found and read", async () => {
    const outcome = await checkContrast({
      ledger: healthy(),
      ledgerFile: await committed(healthy()),
      excusedOnAnInkFill: { "--gone": "a reason for a pairing no rule states" },
    });

    expect(outcome.findings[0]?.message).toContain("--gone");
    expect(outcome.findings[0]?.message).toContain("a reason for a pairing no rule states");
  });
});

/* The staleness rule itself, over both lists, because each has a different notion of the case still existing. */
describe("an excuse that describes nothing", () => {
  it("is reported, whatever the set it was declared in", () => {
    const planted = { "--gone": "a reason for a case that no longer exists" };

    expect(deadExcuses(planted, () => false)).toEqual([
      { ink: "--gone", reason: "a reason for a case that no longer exists" },
    ]);
  });

  it("is not reported while the case it names still exists", () => {
    expect(deadExcuses({ "--here": "still true" }, () => true)).toEqual([]);
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
    const on = (surface: string) => ratioOf(ledger, "--signal-amber", surface) ?? 0;

    expect(on("--paper-raised").toFixed(2)).toBe("4.52");
    expect(on("--paper").toFixed(2)).toBe("4.18");
  });

  /* THE INK FILLS ARE CROSSED AGAINST THE SHEETS, BOTH WAYS, so the constant cannot rot. `--on-ink` is the ink
   * that exists for an ink-filled surface, so the fills the sheets state it onto are exactly the fills that are
   * ink. A third one appearing, or one of these two losing its last rule, reddens here. */
  it("fills with ink in exactly the surfaces the sheets state the inverse ink onto", async () => {
    const ledger = await buildLedger();
    const stated = ledger.composed.filter((one) => one.ink === "--on-ink");

    expect(stated.length).toBeGreaterThan(0);
    expect([...new Set(stated.map((one) => one.surface))].toSorted()).toEqual(
      [...INK_FILLED].toSorted(),
    );
  });

  /* The enforced set on an ink fill, read from the sheets. Non-empty, because a run that found none would hold
   * nothing to the floor, and every one clearing, because the treatment for each is already in its own rule. */
  it("states a pairing on an ink fill in more than one sheet, and every one clears the text floor", async () => {
    const ledger = await buildLedger();
    const stated = textOnAnInkFill(ledger);

    expect(stated.length).toBeGreaterThan(0);
    expect(new Set(stated.map((one) => one.where.split(" ")[0])).size).toBeGreaterThan(1);
    for (const one of stated) {
      const ratio = ratioOf(ledger, one.ink, one.surface) ?? 0;
      expect(ratio, `${one.ink} on ${one.surface} per ${one.where}`).toBeGreaterThanOrEqual(
        TEXT_FLOOR,
      );
    }
  });

  /* A rule states a pairing only when it names both halves, so a rule that replaces its own fill with
   * `transparent` states none: what shows through is the DOM's answer and not the sheet's. That boundary is what
   * keeps this gate from claiming a reachability it cannot derive. */
  it("states no pairing for a rule whose own fill is transparent", async () => {
    const ledger = await buildLedger();

    expect(ledger.composed.filter((one) => one.where.includes(".button--quiet"))).toEqual([]);
  });
});

/* THE UNIT THE READER WORKS IN, which is a selector in a file rather than a block.
 *
 * Two blocks with the same selector compose by the cascade with nothing concatenated, so a pairing split across
 * them is provable from the sheet alone. A reader that took a block at a time would miss it and report `ok`, which
 * is the evasion these cases exist to refuse. Blocks in different at-rule contexts are NOT merged, because two
 * conditions that never both apply state no pairing.
 */
/** The pairings one synthetic sheet states, so the reader's unit can be probed without a fixture in the tree. */
async function statedBy(css: string): Promise<string[]> {
  const directory = await mkdtemp(path.join(tmpdir(), "syncr-usage-"));
  const file = path.join(directory, "probe.css");
  await writeFile(file, css, "utf8");
  const usage = await paletteInUse([file]);
  return usage.compositions.map((one) => `${one.ink} on ${one.surface}`);
}

describe("the pairings a sheet states", () => {
  it("reads a fill and an ink split across two blocks with the same selector", async () => {
    const stated = await statedBy(
      ".probe { background: var(--ink-deep); }\n.probe { color: var(--ink-soft); }\n",
    );

    expect(stated).toEqual(["--ink-soft on --ink-deep"]);
  });

  it("reads them in either order, because the cascade does not care which block came first", async () => {
    const stated = await statedBy(
      ".probe { color: var(--ink-soft); }\n.probe { background: var(--ink-deep); }\n",
    );

    expect(stated).toEqual(["--ink-soft on --ink-deep"]);
  });

  it("takes the last fill, so a later transparent leaves the selector stating nothing", async () => {
    const stated = await statedBy(
      ".probe { background: var(--ink-deep); color: var(--ink-soft); }\n" +
        ".probe { background: transparent; }\n",
    );

    expect(stated).toEqual([]);
  });

  it("states nothing across two selectors that only meet in the DOM", async () => {
    const stated = await statedBy(
      ".probe-host { background: var(--ink-deep); }\n.probe-child { color: var(--ink-soft); }\n",
    );

    expect(stated).toEqual([]);
  });

  /* A fill inside a media query and an ink outside it may never both apply, so merging them would state a pairing
   * that never composes. The key includes the enclosing at-rules for that reason. */
  it("does not merge blocks whose at-rule contexts differ", async () => {
    const stated = await statedBy(
      "@media print { .probe { background: var(--ink-deep); } }\n.probe { color: var(--ink-soft); }\n",
    );

    expect(stated).toEqual([]);
  });

  it("does merge blocks inside the same at-rule", async () => {
    const stated = await statedBy(
      "@media print { .probe { background: var(--ink-deep); } .probe { color: var(--ink-soft); } }\n",
    );

    expect(stated).toEqual(["--ink-soft on --ink-deep"]);
  });
});
