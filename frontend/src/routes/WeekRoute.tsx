/* THE WEEK SCREEN, READ-ONLY.
 *
 * The plan, the strip that reads it, and the two states that replace it when there is no plan. Selection, the
 * discrete drag, keyboard traversal, the verdict panel and the detail panel arrive with whatever owns interaction:
 * every state a block can be in is a prop the grid takes, and this screen passes none of them.
 *
 * THE WEEK IT SHOWS COMES FROM THE URL, and with no `week` parameter it is the one holding today in the reader's own
 * home zone. A mode is reachable by URL in this product, and so is a week: `/week?week=2026-W07` survives a reload
 * and can be linked.
 *
 * NOW IS READ ONCE PER RENDER, not on a timer. The now rule moves when something else causes a redraw, which is
 * every minute the reader is doing anything and never while they are reading: a rule that advanced on its own would
 * be the one moving thing in a product whose motion is zero. */

import { useSearchParams } from "react-router";

import { useWeekSolve } from "../api/hooks/useWeek";
import { useSettings } from "../api/hooks/useSettings";
import { todayIn } from "../lib/zonedInstant";
import { EmptyWeek, SummaryStrip, WeekGrid } from "../ui/domain";
import { ErrorState, PendingState } from "../ui/domain";
import { RouteBand } from "./RouteBand";
import { isoWeekOf } from "./today/isoWeek";
import { columnLabel, weekRange } from "./week/labels";
import { useWeekScreen } from "./week/useWeekScreen";

const SETUP_HREF = "/setup";
const SETTINGS_HREF = "/settings";

export function WeekRoute() {
  const [params] = useSearchParams();
  const settings = useSettings();
  const homeZone = settings.status === "ready" ? settings.data.homeZone : "UTC";
  const isoWeek = params.get("week") ?? isoWeekOf(todayIn(homeZone, Date.now())) ?? "";
  const screen = useWeekScreen(isoWeek);
  const solve = useWeekSolve();

  if (screen.status === "loading") {
    return (
      <RouteBand title="Week" sub={isoWeek}>
        <PendingState title="Reading this week" detail="The plan will arrive in one redraw." />
      </RouteBand>
    );
  }

  if (screen.status === "error") {
    return (
      <RouteBand title="Week" sub={isoWeek}>
        <ErrorState title="This week was not read" detail={screen.problem.detail} />
      </RouteBand>
    );
  }

  if (screen.status === "empty") {
    return (
      <RouteBand title="Week" sub={isoWeek}>
        <EmptyWeek
          extendHorizonHref={SETTINGS_HREF}
          onSolveNow={() => {
            void solve.submit({ isoWeek, isImmediate: true });
          }}
          reason={screen.reason}
          setupHref={SETUP_HREF}
          statement={screen.facts.statement}
        />
      </RouteBand>
    );
  }

  const dates = screen.days.map((day) => day.date);
  return (
    <RouteBand title="Week" sub={`${isoWeek} · ${weekRange(dates)}`}>
      <SummaryStrip readings={screen.readings} verdict={null} />
      <WeekGrid
        days={screen.days}
        extent={screen.extent}
        labels={dates.map(columnLabel)}
        nowMs={Date.now()}
        visibleHours={screen.visibleHours}
      />
    </RouteBand>
  );
}
