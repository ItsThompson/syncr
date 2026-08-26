/* THE WALK `z` TAKES THROUGH THE RANGE THE GRID REPORTED, and why it is the report's levels and not a ladder of
 * this screen's own. The offerable range is 6 to 24 with its upper end clamped PER DISPLAY, from a measurement
 * only the grid has: a ladder named here would be named from no measurement at all, and this one was -- it cycled
 * onto 20 on a display whose cap is 16 and let the grid silently redraw 16 instead. So the walk follows the report
 * hour by hour, skips every level whose own refusal the report states, and wraps past the top, which is where the
 * walk ends that a cap would otherwise strand: from 16 on a six-hundred-pixel grid one press lands on 6, and
 * nothing past the cap is ever proposed. */

import type { ZoomReport } from "../../ui/domain";

/** The first available level after the current one, wrapping past the top of the report's range.
 *
 * Null only where there is nothing to walk -- before the grid has reported, or on a report offering no level at
 * all, which the floor makes unreachable but a walk must survive rather than loop in. */
export function nextAvailableHours(report: ZoomReport | null, current: number): number | null {
  if (report === null) return null;
  const levels = report.levels;
  if (levels.length === 0) return null;
  /* From below the floor or above the ceiling the walk starts at the range's own ends, never off its edge. */
  const found = levels.findIndex((level) => level.hours >= current);
  const start = found === -1 ? 0 : found;
  for (let step = 1; step <= levels.length; step += 1) {
    const candidate = levels[(start + step) % levels.length];
    if (candidate.isAvailable) return candidate.hours;
  }
  return null;
}
