/* THE CONTRAST LEDGER: EVERY INK THE PRODUCT DRAWS WITH, AGAINST EVERY SURFACE IT FILLS WITH, COMPUTED.
 *
 * The design language's accessibility rule is not "the expected pair clears its floor". It is that a colour clears
 * it against EVERY surface it can appear on, and the reason is a measured one: `--signal-amber` clears 4.52:1 on
 * raised paper and 4.18:1 on the page, so a label in it passes on one surface and fails on the other. A pair
 * checked only where its author expected it is how amber came to have no text step at all.
 *
 * SO THE LEDGER IS THE WHOLE MATRIX, and reachability is not guessed. Which surface a given class sits on is a
 * fact about the DOM, which no stylesheet states and no static reading can recover; the honest alternative is to
 * measure each ink against all of them and record the verdict per cell. A cell that fails is not automatically a
 * defect -- `--on-ink` on `--paper` is 1.08:1 and could not be otherwise -- but a cell with NO RATIO is a pair
 * nobody has measured, and that is what this refuses.
 *
 * THREE CONCERNS, THREE FILES. What a token can hold is `resolution.ts`; which tokens the sheets draw and fill
 * with is `usage.ts`; the WCAG formula and the two floors are `scripts/lib/contrast.ts`, shared with the kit's own
 * suites so the audit's floors have one home. What is left here is the matrix itself. */

import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, tokenDir } from "../lib/paths.ts";
import { INDICATOR_FLOOR, TEXT_FLOOR, contrastRatio } from "../lib/contrast.ts";
import { assignments, coloursOf, hexOf, type Unmeasurable } from "./resolution.ts";
import { paletteInUse, type Composition, type InkUse } from "./usage.ts";

export { INDICATOR_FLOOR, TEXT_FLOOR, contrastRatio };
export type { Unmeasurable };

/* THE FILLS THAT ARE INK RATHER THAN PAPER, which is where an ink written for paper stops being readable.
 * `--on-ink` exists for exactly these, so the list is crossable against the sheets rather than trusted: every
 * pairing a rule states with `--on-ink` names one of these fills and no other. The audit's cases assert that in
 * both directions, so a third ink fill cannot appear without this constant moving. */
export const INK_FILLED = ["--ink", "--ink-deep"] as const;

export interface Pair {
  readonly ink: string;
  readonly surface: string;
  readonly ratio: number;
  /** The floor the strictest shipped use of this ink has to clear. */
  readonly floor: number;
  /** The declaration that set that floor, so the classification can be checked. */
  readonly floorFrom: string;
  readonly clears: boolean;
}

/** A pairing a single rule states, with both halves resolved to the names the matrix reports. */
export interface Composed {
  /** The rule that states it, so a finding names something a reader can open. */
  readonly where: string;
  readonly ink: string;
  readonly surface: string;
  readonly floor: number;
}

export interface Ledger {
  readonly inks: readonly string[];
  readonly surfaces: readonly string[];
  readonly pairs: readonly Pair[];
  readonly unmeasurable: readonly Unmeasurable[];
  /** Every stylesheet the palette was read from, so the ledger says what it covered. */
  readonly sheets: readonly string[];
  /** The pairings the sheets state outright, which are the ones a floor can be enforced on off paper. */
  readonly composed: readonly Composed[];
}

/** The ledger: every ink against every surface, with the ratio each pair measures. */
export async function buildLedger(): Promise<Ledger> {
  const sheets = (await filesUnder(appSourceDir, [".css"])).filter(
    (file) => !file.startsWith(`${tokenDir}${path.sep}`),
  );
  const usage = await paletteInUse(sheets);
  const held = await assignments(sheets);
  const unmeasurable: Unmeasurable[] = [...usage.mixes];

  const uses = new Map<string, InkUse>();
  for (const [token, use] of usage.inks) {
    const resolved = coloursOf(held, token);
    unmeasurable.push(...resolved.unmeasurable);
    for (const ink of resolved.tokens) {
      const carried = uses.get(ink);
      if (carried === undefined || use.floor > carried.floor) uses.set(ink, use);
    }
  }

  const surfaces = new Set<string>();
  for (const token of usage.surfaces) {
    const resolved = coloursOf(held, token);
    unmeasurable.push(...resolved.unmeasurable);
    for (const surface of resolved.tokens) surfaces.add(surface);
  }

  const inks = [...uses.keys()].toSorted();
  const surfaceNames = [...surfaces].toSorted();
  const pairs: Pair[] = [];
  for (const ink of inks) {
    const use = uses.get(ink) ?? { floor: INDICATOR_FLOOR, where: "nothing" };
    for (const surface of surfaceNames) {
      const ratio = contrastRatio(hexOf(held, ink), hexOf(held, surface));
      pairs.push({
        ink,
        surface,
        ratio,
        floor: use.floor,
        floorFrom: use.where,
        clears: ratio >= use.floor,
      });
    }
  }

  return {
    inks,
    surfaces: surfaceNames,
    pairs,
    unmeasurable: deduplicate(unmeasurable),
    sheets: usage.sheets,
    composed: resolveComposed(held, usage.compositions),
  };
}

/**
 * The stated pairings, with both halves put through the same resolution the matrix uses.
 *
 * A carrier resolves to several colours, so one rule can state several pairings, and a token that resolves to no
 * flat colour states none: whatever it holds is already recorded as unmeasurable with its reason.
 */
function resolveComposed(
  held: ReadonlyMap<string, Set<string>>,
  stated: readonly Composition[],
): Composed[] {
  const byKey = new Map<string, Composed>();
  for (const one of stated) {
    for (const ink of coloursOf(held, one.ink).tokens) {
      for (const surface of coloursOf(held, one.surface).tokens) {
        byKey.set(`${one.where} ${ink} ${surface}`, {
          where: one.where,
          ink,
          surface,
          floor: one.floor,
        });
      }
    }
  }
  return [...byKey.values()].toSorted((one, two) => one.where.localeCompare(two.where));
}

function deduplicate(found: readonly Unmeasurable[]): Unmeasurable[] {
  const byKey = new Map<string, Unmeasurable>();
  for (const one of found) byKey.set(`${one.token} ${one.value}`, one);
  return [...byKey.values()].toSorted((one, two) => one.token.localeCompare(two.token));
}

/** Every ink the ledger holds to the text floor, which is every ink a `color` declaration writes. */
export function textInks(ledger: Ledger): string[] {
  return ledger.inks.filter(
    (ink) => ledger.pairs.find((pair) => pair.ink === ink)?.floor === TEXT_FLOOR,
  );
}

/** The pairings a rule states that put text on an ink fill, which is the reachable set off paper. */
export function textOnAnInkFill(ledger: Ledger): Composed[] {
  const fills = new Set<string>(INK_FILLED);
  return ledger.composed.filter((one) => one.floor === TEXT_FLOOR && fills.has(one.surface));
}

/**
 * Every stated pairing that does not clear the floor its own property implies, over every floor.
 *
 * Wider than what any rule enforces, on purpose: an indicator's stated pairing below the indicator floor is a
 * measurement the audit can make and a verdict it does not reach, because whether a given property is an indicator
 * is a design classification rather than a ratio.
 */
export function statedBelowItsFloor(ledger: Ledger): Composed[] {
  return ledger.composed.filter((one) => {
    const ratio = ratioOf(ledger, one.ink, one.surface);
    return ratio === null || ratio < one.floor;
  });
}

/** The ratio a pair measures, or null when the matrix has no such cell. */
export function ratioOf(ledger: Ledger, ink: string, surface: string): number | null {
  return ledger.pairs.find((pair) => pair.ink === ink && pair.surface === surface)?.ratio ?? null;
}
