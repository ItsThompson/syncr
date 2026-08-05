/* THE WEEK SCREEN'S OWN READS, AND THE MODEL IT HANDS THE GRID.
 *
 * Three resources rather than one, because the api serves three and they change for different reasons: the week's
 * plan changes when a solve lands, the Areas change when one is declared, and the two grid preferences change when
 * the reader changes them. Composing the WEEK is the server's job and composing the SCREEN is this hook's.
 *
 * A COMPONENT NEVER FETCHES, so the grid is handed `WeekDay`s and knows nothing about a response. What the hook
 * returns is either the model or the reason there is no plan, as one discriminated state: a screen cannot then
 * render a grid and an empty state at once, which two independent booleans would let it. */

import { useAreas } from "../../api/hooks/useAreas";
import { useSettings } from "../../api/hooks/useSettings";
import {
  useWeek,
  type EmptyWeekFacts,
  type WeekReadings,
  type WeekView,
} from "../../api/hooks/useWeek";
import { parseClock } from "../../ui/primitives";
import type { Extent, WeekDay } from "../../ui/domain";
import type { Problem } from "../../contract";
import { bandOfEmptySlot, bandOfOffPlanPeriod, bandOfWindow, type WeekBand } from "./bands";
import { areaIndexOf, weekBlockOf } from "./blocks";
import { weekModel, type DayBounds } from "./weekModel";

/** What the screen renders, as one state rather than as several independent readings. */
export type WeekScreenState =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly problem: Problem }
  | {
      readonly status: "empty";
      readonly reason: "outside_horizon" | "setup_incomplete";
      readonly facts: EmptyWeekFacts;
    }
  | {
      readonly status: "ready";
      readonly days: readonly WeekDay[];
      readonly extent: Extent;
      readonly visibleHours: number;
      readonly readings: WeekReadings;
    };

/** The declared bounds, from two wall times the settings carry. An unreadable one falls back to the whole day. */
export function boundsOf(dayStart: string, dayEnd: string): DayBounds {
  return { startMin: parseClock(dayStart) ?? 0, endMin: parseClock(dayEnd) ?? 0 };
}

export function useWeekScreen(isoWeek: string): WeekScreenState {
  const week = useWeek(isoWeek);
  const areas = useAreas();
  const settings = useSettings();

  if (week.status === "error") return { status: "error", problem: week.problem };
  if (areas.status === "error") return { status: "error", problem: areas.problem };
  if (settings.status === "error") return { status: "error", problem: settings.problem };
  if (week.status === "loading" || areas.status === "loading" || settings.status === "loading") {
    return { status: "loading" };
  }

  const view = week.data;
  if (view.live === null || view.readings === null) return emptyState(view);

  return {
    status: "ready",
    ...weekModel({
      zoneByDate: view.live.zoneByDate,
      spanEnd: view.span.end,
      bounds: boundsOf(settings.data.dayStart, settings.data.dayEnd),
      blocks: view.live.blocks.map((block) => weekBlockOf(block, areaIndexOf(areas.data.areas))),
      bands: bandsOf(view),
    }),
    /* The setting travels as the reader stored it. `WeekGrid` brings it inside the range its OWN measured height
     * offers, because this hook has no measurement: clamping here would cap every display at the reference
     * display's, which renders a 27 inch reader's stored 24 as 16 and, on a window shorter than the reference,
     * offers a level at which the modal block loses its title. */
    visibleHours: settings.data.visibleHours,
    readings: view.readings,
  };
}

/* THE THREE KINDS OF GAP, ASSEMBLED IN THE ORDER THEY DRAW IN, which is any order at all: they share one drawing
 * rule, so the grid needs no discriminant and this list needs no sort. */
function bandsOf(view: WeekView): WeekBand[] {
  if (view.live === null) return [];
  return [
    ...view.live.forbiddenWindows.map(bandOfWindow),
    ...view.live.emptySlots.map(bandOfEmptySlot),
    ...view.offPlan.map(bandOfOffPlanPeriod),
  ];
}

/**
 * The empty state, which is a real rendering rather than an absence.
 *
 * `emptyReason` is null exactly when `live` is populated, so reaching here with neither is a response the server
 * does not produce. It is treated as the loading state rather than as an error: nothing is broken, and there is
 * nothing yet to draw.
 */
function emptyState(view: WeekView): WeekScreenState {
  if (view.emptyReason === null || view.emptyWeek === null) return { status: "loading" };
  return { status: "empty", reason: view.emptyReason, facts: view.emptyWeek };
}
