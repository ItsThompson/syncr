/* Every read the Settings screen makes, stubbed for one state.
 *
 * SIX READS, ONE HELPER. The screen narrows them into four readings and every test needs all six answered, so a
 * per-test set of handlers is how one of them comes to stub five and assert against a failure surface by accident.
 *
 * A HANDLER INSTALLED FIRST WINS, which is msw's own rule, so a case that varies one read passes its own handler
 * ahead of this set rather than after it. */

import type { RequestHandler } from "msw";

import { jsonHandler, readyz } from "../../../testing/apiStub";
import { buildConnection, buildRoutine, buildSettings, buildSource } from "./fixtures";
import type { CalendarSource, GoogleConnection } from "../../../api/hooks/useCalendarSources";
import type { OffPlanPeriod } from "../../../api/hooks/useOffPlan";
import type { Routine } from "../../../api/hooks/useRoutines";
import type { Settings, TravelOverride } from "../../../api/hooks/useSettings";

export interface SettingsState {
  readonly settings?: Settings;
  readonly overrides?: readonly TravelOverride[];
  readonly sources?: readonly CalendarSource[];
  /** The notices the api composes about those sources, staleness among them. */
  readonly sourceNotices?: readonly Record<string, unknown>[];
  readonly connection?: GoogleConnection;
  readonly routines?: readonly Routine[];
  readonly periods?: readonly OffPlanPeriod[];
}

/** The uninteresting case: one working feed, no travel, no time off, an inelastic sleep routine. */
export function settingsHandlers(state: SettingsState = {}): RequestHandler[] {
  return [
    readyz(),
    jsonHandler("/api/v1/settings", { status: 200, body: state.settings ?? buildSettings() }),
    jsonHandler("/api/v1/settings/travel-overrides", {
      status: 200,
      body: { overrides: state.overrides ?? [] },
    }),
    jsonHandler("/api/v1/calendar-sources", {
      status: 200,
      body: {
        sources: state.sources ?? [buildSource()],
        notices: state.sourceNotices ?? [],
      },
    }),
    jsonHandler("/api/v1/calendar-sources/google/connection", {
      status: 200,
      body: state.connection ?? buildConnection(),
    }),
    jsonHandler("/api/v1/routines", {
      status: 200,
      body: { routines: state.routines ?? [buildRoutine()] },
    }),
    jsonHandler("/api/v1/off-plan", { status: 200, body: { periods: state.periods ?? [] } }),
  ];
}
