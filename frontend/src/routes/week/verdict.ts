/* THE WIRE'S VERDICT, NARROWED TO WHAT THE PANEL AND THE STRIP RENDER.
 *
 * The kit does not know what a response is, so this is where an Area id becomes an Area's name, an instant becomes a
 * reading in the week's own zone, and minutes become `1h20m`. One narrowing for both surfaces, so the strip's verdict
 * cell and the panel cannot state one week two ways.
 *
 * A SHORTFALL'S IDENTITY IS ITS KIND PLUS WHAT IT IS AGAINST. The wire carries no identifier for a gap, and it does
 * not need one: a verdict never reports two gaps of one kind against one commitment, because the probe groups its
 * demands before it measures them. Keying on the pair rather than on the array index means a list that gains a gap
 * does not re-key the ones beside it.
 *
 * THE DEADLINE IS READ IN THE WEEK'S OWN ZONE, not the browser's. A reader east of their own plan would otherwise see
 * a Friday deadline reported as Saturday, which is exactly the class of defect the zone map exists to prevent.
 *
 * WHAT A CONCESSION RECOVERS IS A CEILING, AND IT IS WORDED AS ONE HERE. The api sizes that figure as an upper bound
 * on the movement approving the concession produces: three of its measurements can state more than approving it
 * delivers and none can state less. So the bound travels with the figure out of this narrowing rather than being
 * added by whichever surface renders it, which is what stops a second surface stating the same number as a fact. */

import {
  formatMinutes,
  verdictDetail,
  verdictHeadline,
  type PanelVerdict,
  type VerdictConcession,
} from "../../ui/domain";
import type { VerdictShortfall, VerdictTradeoff } from "../../ui/domain";
import type { components } from "../../api/schema";
import type { WeekReadingsContext } from "./readings";

type Verdict = components["schemas"]["VerdictResponse"];
type Shortfall = components["schemas"]["ShortfallResponse"];
type Tradeoff = components["schemas"]["TradeoffResponse"];
type Adjustment = components["schemas"]["AdjustmentResponse"];

/** How a concession reads when the api sent no wording for it, which the adjustment resource does not. */
const CONCESSION_WORDING: Readonly<Record<Adjustment["kind"], string>> = {
  drop_item: "An item was dropped for this week",
  reduce_routine: "A routine was shortened for this week",
  breach_floor: "An Area floor was breached for this week",
  accept_partial: "Partial delivery was accepted for this week",
};

export function panelVerdictOf(verdict: Verdict, zone: WeekReadingsContext): PanelVerdict {
  return {
    provenance: verdict.provenance,
    isFeasible: verdict.feasible,
    capacityIsSufficient: verdict.capacityIsSufficient,
    shortfalls: verdict.shortfalls.map((gap) => shortfallOf(gap, zone)),
    tradeoffs: verdict.tradeoffs.map(tradeoffOf),
  };
}

/** The strip's verdict cell: one sentence, and the gap behind it, from the same narrowing the panel renders. */
export function stripVerdictOf(
  verdict: PanelVerdict,
  concessionCount: number,
): { readonly headline: string; readonly detail: string } {
  return {
    headline: verdictHeadline(verdict, concessionCount),
    detail: verdictDetail(verdict),
  };
}

function shortfallOf(gap: Shortfall, zone: WeekReadingsContext): VerdictShortfall {
  return {
    id: `${gap.kind}:${gap.against.join("|")}`,
    kind: gap.kind,
    shortfall: formatMinutes(gap.minutes),
    against: gap.against,
    honoring: gap.honoring,
    deadline:
      gap.deadline === null || gap.deadline === undefined ? null : zone.instant(gap.deadline),
  };
}

function tradeoffOf(tradeoff: Tradeoff): VerdictTradeoff {
  return {
    kind: tradeoff.kind,
    label: tradeoff.label,
    targetId: tradeoff.targetId,
    recovers:
      tradeoff.deltaMinutes === null || tradeoff.deltaMinutes === undefined
        ? null
        : `up to ${formatMinutes(tradeoff.deltaMinutes)}`,
  };
}

/**
 * The concessions this week has already absorbed, in the order the assembler folds them.
 *
 * THE WORDING IS COMPOSED HERE AND THE FIGURE IS THE WIRE'S. An adjustment resource carries a kind, a target and a
 * delta but no sentence, unlike a tradeoff, which carries the wording it was offered with. So the reading names the
 * kind and quotes the delta, and it does not attempt to name the target: resolving a routine id or a task id to a
 * name would need two more reads on the densest screen in the product, and the delta is what the reader is owed.
 */
export function concessionsOf(
  adjustments: readonly Adjustment[],
  zone: WeekReadingsContext,
): VerdictConcession[] {
  return adjustments.map((adjustment) => ({
    id: adjustment.id,
    label: labelOf(adjustment),
    approvedOn: zone.date(adjustment.createdAt),
  }));
}

function labelOf(adjustment: Adjustment): string {
  const wording = CONCESSION_WORDING[adjustment.kind];
  const minutes = adjustment.deltaMinutes;
  const perDate = Object.values(adjustment.reductions).reduce((sum, each) => sum + each, 0);
  if (minutes !== null && minutes !== undefined) return `${wording}, by ${formatMinutes(minutes)}`;
  if (perDate > 0) {
    const nights = Object.keys(adjustment.reductions).length;
    return `${wording}, by ${formatMinutes(perDate)} across ${String(nights)} dates`;
  }
  return wording;
}
