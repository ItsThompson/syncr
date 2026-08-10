/* THE INKS EXCUSED FROM A FLOOR, ENUMERATED RATHER THAN RECOGNISED.
 *
 * One list per surface class, because an ink excused on paper is not thereby excused on an ink fill and the
 * reverse. `--on-ink` is excused on paper for measuring 1.08:1 there, and it is the ink of every pairing the
 * sheets state on an ink fill: one shared list would excuse it in both places and leave the ink-fill rule
 * enforcing nothing.
 *
 * Every excuse is held to describing something real, in both directions. An excuse for a case that no longer
 * exists is an excuse nobody can check, so the staleness rule reports it: that is `deadExcuses`, which both lists
 * share with a different notion of "still exists". */

/** An excuse whose case no longer exists, so the excuse describes nothing. */
export interface DeadExcuse {
  readonly ink: string;
  readonly reason: string;
}

/** A list of inks excused from a floor, each with the reason and the guard that replaces the ratio. */
export type Excuses = Readonly<Record<string, string>>;

/**
 * The inks excused from the text floor on a paper surface.
 *
 * All three are inks a `color` declaration writes, so the derivation finds them, and each is excused for a reason
 * a ratio cannot express: one is not on paper at all, one is not text, and one is a track rather than a reading.
 *
 * Exported so a synthetic ledger can carry the real set: a fixture that omitted them would leave every excuse
 * describing nothing, which the staleness rule refuses, and a fourth excuse added here then appears in the
 * fixtures by itself.
 */
export const EXCUSED_FROM_THE_TEXT_FLOOR: Excuses = {
  "--on-ink":
    "it exists for an ink-filled surface and measures 14.83:1 there. On paper it is 1.08:1 and could " +
    "not be otherwise; what keeps it off paper is that the only rules writing it are an ink header's own",
  "--signal-amber":
    "amber has no text step: it is written on a MARK, which is an indicator at 3:1, and it measures " +
    "4.52:1 on raised paper against 4.18:1 on the page. What forbids it on prose is structural rather " +
    "than numeric, in src/ui/domain/__tests__/pigment.test.ts, which refuses a signal pigment on any " +
    "selector that is not always a glyph",
  "--rule":
    "the one declaration writing it as text is the bounded meter's UNFILLED run, which is a track " +
    "rather than a reading: every cell is aria-hidden, the value is on the meter's own role, and the " +
    "row states the samples and the percentage beside it. charts.css carries that disclosure at the " +
    "rule itself, with the 1.71:1 figure",
};

/** Every ink the paper enforcement excuses, for a case that needs the set rather than the reasons. */
export const EXCUSED_TEXT_INKS: readonly string[] = Object.keys(EXCUSED_FROM_THE_TEXT_FLOOR);

/**
 * The inks excused from the text floor on an ink-filled surface.
 *
 * EMPTY, AND THAT IS A MEASUREMENT RATHER THAN AN OMISSION. Every pairing the sheets state on an ink fill is
 * `--on-ink`, at 11.50:1 on `--ink` and 14.83:1 on `--ink-deep`, so nothing needs excusing. The list is declared
 * because the day a rule states an ink fill under an ink that cannot clear there, the choice is to fix the rule
 * or to say here why a ratio is the wrong instrument for it.
 *
 * The gate takes both lists as INPUT rather than reading them from this module, so both the staleness rule and the
 * skip an entry produces are reachable while this list is empty. A guard reached by nothing is the same decoration
 * as no guard.
 */
export const EXCUSED_ON_AN_INK_FILL: Excuses = {};

/**
 * The excuses that describe nothing, which is the staleness rule run in the other direction.
 *
 * `describesSomething` is the caller's notion of the case still existing: an ink the product still writes as text,
 * or a pairing some rule still states.
 */
export function deadExcuses(
  excused: Excuses,
  describesSomething: (ink: string) => boolean,
): DeadExcuse[] {
  return Object.entries(excused).flatMap(([ink, reason]) =>
    describesSomething(ink) ? [] : [{ ink, reason }],
  );
}
