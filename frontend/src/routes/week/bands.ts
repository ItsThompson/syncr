/* THE THREE KINDS OF EXPLAINED GAP, MAPPED ONTO THE ONE THING THE GRID DRAWS.
 *
 * A forbidden window, an off-plan period and an unfilled template slot are three distinct types, because the
 * discretionary-time denominator treats each differently: a window and an off-plan span leave it, and an empty
 * slot stays in it. They DRAW identically, because what all three explain is the same thing, that nothing is
 * there. `ForbiddenBand` therefore takes no kind at all: the only thing that varies between them is the
 * sentence in the gutter, and a drawing rule cannot diverge when there is nothing to diverge on.
 *
 * A GAP IS DRAWN RATHER THAN OMITTED. Left as nothing, a forbidden gap and an ordinary empty gap are
 * pixel-identical and the solver appears to decline a gap for no reason.
 *
 * EVERY GUTTER SENTENCE IS THE PAYLOAD'S, AND NONE IS COMPOSED HERE. Each empty-slot reason maps to exactly one
 * wording and `syncr_domain.gaps.gutter_label` is that one statement; it is Python, a wording may substitute the
 * Area's name, and the wire carries the rendered string, so this module reads it. Composing it here from the
 * reason code would be the second statement the one-wording rule exists to forbid, and would have to be kept in
 * step with a vocabulary that grows. The reason code travels beside the label, so a client keying on the code
 * keeps working. A window's label is the STORED one, so an anchor retitled in March cannot change what a week
 * approved in February says, and an off-plan span's is the user's own word for it, which they need not have
 * given. */

import type { GridBand } from "../../ui/domain";
import type { components } from "../../api/schema";

type ForbiddenWindow = components["schemas"]["ForbiddenWindowResponse"];
type EmptySlot = components["schemas"]["EmptySlotResponse"];
type OffPlanPeriod = components["schemas"]["OffPlanPeriodResponse"];

/** A band before it is placed in a column: the instants it covers, and what it says. */
export interface WeekBand {
  readonly id: string;
  readonly startMs: number;
  readonly endMs: number;
  readonly label: string | null;
  readonly reason: GridBand["reason"];
}

export function bandOfWindow(window: ForbiddenWindow): WeekBand {
  return {
    id: `forbidden:${window.anchorId}:${window.interval.start}`,
    startMs: Date.parse(window.interval.start),
    endMs: Date.parse(window.interval.end),
    label: window.label,
    reason: window.kind,
  };
}

/** A declared off-plan span. Its label is the user's own word for it, and null where they gave it none. */
export function bandOfOffPlanPeriod(period: OffPlanPeriod): WeekBand {
  return {
    id: `off-plan:${period.id}`,
    startMs: Date.parse(period.start),
    endMs: Date.parse(period.end),
    label: period.label,
    reason: "off_plan",
  };
}

/** A template slot the solver could not fill. The wire carries its one wording, and the reason beside it. */
export function bandOfEmptySlot(slot: EmptySlot): WeekBand {
  return {
    id: `empty-slot:${slot.areaId}:${slot.interval.start}`,
    startMs: Date.parse(slot.interval.start),
    endMs: Date.parse(slot.interval.end),
    label: slot.label,
    reason: slot.reason,
  };
}
