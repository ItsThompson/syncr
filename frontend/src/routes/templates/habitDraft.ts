/* The habit editor's draft, and the patch body it becomes.
 *
 * THE FORM REFUSES ONLY WHAT IT CANNOT EXPRESS. A cadence count arrives as typed text, so text that is not a
 * whole number is not a body at all and the form says which member to complete. Every BOUND and every
 * RELATION belongs to the api: a count of zero, a debt cap of ninety, a ceiling under its floor are all sent
 * and all refused with the member named, and restating those rules here would put a second copy of each one in
 * the browser, free to drift from the one the table's own constraints hold.
 *
 * NEITHER DERIVATION IS A MEMBER OF THIS DRAFT. The rotation cursor and the debt figure are projections of the
 * outcome log, the patch shape has no member for either, and an unknown member is refused. A control that set
 * one would have nothing to send: correcting a wrong cursor is correcting the day it came from.
 *
 * THE AREA IS NOT A MEMBER EITHER. It is declared once, because moving it would re-attribute hours already
 * reported.
 *
 * Pure: no React, no client, no DOM. */

import type { Habit, HabitEdit } from "../../api/hooks/useHabits";
import type { components } from "../../api/schema";

export type CadenceKind = components["schemas"]["CadenceKind"];
export type MissPolicy = components["schemas"]["MissPolicy"];
type CadenceBody = components["schemas"]["CadenceRequest"];

export interface HabitDraft {
  readonly title: string;
  readonly cadenceKind: CadenceKind;
  /** As typed: the count for a weekly cadence, the interval in days for an approximate one. */
  readonly cadenceCount: string;
  readonly minDurationMinutes: number;
  readonly maxDurationMinutes: number;
  readonly missPolicy: MissPolicy;
  /** As typed. The ceiling on outstanding debt, in cadence periods. */
  readonly debtCapPeriods: string;
}

export type HabitMember = "title" | "cadenceCount" | "debtCapPeriods";

export type HabitProposal =
  | { readonly status: "declarable"; readonly body: HabitEdit }
  | { readonly status: "incomplete"; readonly member: HabitMember; readonly reason: string };

/** A whole count, or null when the text is not one. `Number("")` is 0, so this cannot be `Number`. */
function wholeCount(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  return Number(trimmed);
}

/** Which number the kind uses. A daily cadence uses neither, and the api refuses the one it does not use. */
function cadenceOf(kind: CadenceKind, count: number): CadenceBody {
  if (kind === "times_per_week") return { kind, timesPerWeek: count };
  if (kind === "every_approx_days") return { kind, approxDays: count };
  return { kind };
}

export function habitDraftFrom(habit: Habit): HabitDraft {
  const count = habit.cadence.timesPerWeek ?? habit.cadence.approxDays;
  return {
    title: habit.title,
    cadenceKind: habit.cadence.kind,
    cadenceCount: count === null || count === undefined ? "" : String(count),
    minDurationMinutes: habit.minDurationMinutes,
    maxDurationMinutes: habit.maxDurationMinutes,
    missPolicy: habit.missPolicy,
    debtCapPeriods: String(habit.debtCapPeriods),
  };
}

export function habitProposalFrom(draft: HabitDraft): HabitProposal {
  if (draft.title.trim() === "") {
    return {
      status: "incomplete",
      member: "title",
      reason: "A habit is named. The title is what a block carries on the grid and in the ledger.",
    };
  }

  const cap = wholeCount(draft.debtCapPeriods);
  if (cap === null) {
    return {
      status: "incomplete",
      member: "debtCapPeriods",
      reason:
        "The cap is a whole number of cadence periods: 2 means two periods' worth of occurrences.",
    };
  }

  /* A daily cadence carries no number, so an unparseable count is irrelevant to it: refusing on a member the
   * body will not hold would leave a reader unable to save a daily habit until they cleared a box the request
   * never sends. */
  const isCountUsed = draft.cadenceKind !== "daily";
  const count = wholeCount(draft.cadenceCount);
  if (isCountUsed && count === null) {
    return {
      status: "incomplete",
      member: "cadenceCount",
      reason:
        draft.cadenceKind === "times_per_week"
          ? "A weekly cadence is a whole count of occurrences: 4 is four times a week."
          : "An approximate cadence is a whole interval in days: 7 is roughly weekly.",
    };
  }

  return {
    status: "declarable",
    body: {
      title: draft.title.trim(),
      cadence: cadenceOf(draft.cadenceKind, count ?? 0),
      minDurationMinutes: draft.minDurationMinutes,
      maxDurationMinutes: draft.maxDurationMinutes,
      missPolicy: draft.missPolicy,
      debtCapPeriods: cap,
    },
  };
}
