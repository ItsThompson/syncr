/* THE WEEK SCREEN. The plan, the strip that reads it, the verdict at the head, the panel that explains one block, and
 * the interaction the whole asynchronous design exists to serve.
 *
 * THE WEEK IT SHOWS COMES FROM THE URL, and with no `week` parameter it is the one holding today in the reader's own
 * home zone. A mode is reachable by URL in this product, and so is a week: `/week?week=2026-W07` survives a reload and
 * can be linked, which is also what makes `[`, `]` and `T` navigations rather than state.
 *
 * NOW IS READ ONCE PER RENDER, not on a timer. The now rule moves when something else causes a redraw, which is every
 * minute the reader is doing anything and never while they are reading: a rule that advanced on its own would be the
 * one moving thing in a product whose motion is zero.
 *
 * THE DETAIL PANEL IS FIXED AND THE GRID ABSORBS WHAT IS LEFT. Below --bp-wide the panel closes to a rail rather than
 * narrowing, because a narrower panel cannot hold a reason and a narrower grid cannot hold a title.
 *
 * THE WEEKLY SESSION IS A MODE OF THIS SCREEN, at `?mode=session`, and it is a BRANCH here rather than a route of its
 * own: a second route would be a second destination, and the point of a mode is that it is a way of using the screen.
 * The mode reads one payload of its own for the retrospective and the raises, and draws the grid, the strip, the verdict
 * panel and the approve action from the readings this route already holds -- so the session and the screen cannot
 * disagree about the week. It is triggered only by that URL: nothing here schedules it and nothing nags.
 *
 * OPENING THE MODE DECLARES ITSELF TO THE API CLIENT, which is what puts `session_mode_active` on every mutation the
 * mode makes. One place decides it, so a write added later cannot forget; `api/sessionMode.ts` carries the reasoning.
 *
 * COMPOSITION ONLY. What is selected, what a key does, what a drop sends and what the last response said are
 * `useWeekScreenInteraction`'s; the reads are `useWeekScreen`'s; the words are `verdict.ts`'s and `reasons.ts`'s. What
 * is here is which surface each reading draws on, and in what order a reader meets them. */

import { useEffect } from "react";
import { useSearchParams } from "react-router";

import { setSessionModeOpen } from "../api/sessionMode";
import { useAreas } from "../api/hooks/useAreas";
import { useSettings } from "../api/hooks/useSettings";
import { useWeeklySession } from "../api/hooks/useWeeklySession";
import { todayIn } from "../lib/zonedInstant";
import { EmptyWeek, ErrorState, PendingState, SummaryStrip } from "../ui/domain";
import { RouteBand } from "./RouteBand";
import { isoWeekOf } from "./today/isoWeek";
import { WeekActions } from "./week/components/WeekActions";
import { WeekHead } from "./week/components/WeekHead";
import { WeekSurface } from "./week/components/WeekSurface";
import { weekRange } from "./week/labels";
import { isSessionMode, SessionMode, sessionPath } from "./week/session";
import { SessionHeader } from "./week/session/components/SessionHeader";
import { useWeekScreen } from "./week/useWeekScreen";
import { useWeekScreenInteraction } from "./week/hooks/useWeekScreenInteraction";
import { useWeekWords } from "./week/hooks/useWeekWords";

const SETUP_HREF = "/setup";
const SETTINGS_HREF = "/settings";
const FALLBACK_VISIBLE_HOURS = 12;

/* A stable empty list, so a render before the Areas arrive does not hand the mode a fresh array every time. */
const NO_AREAS: readonly never[] = [];

export function WeekRoute() {
  const [params] = useSearchParams();
  const settings = useSettings();
  const homeZone = settings.status === "ready" ? settings.data.homeZone : "UTC";
  const today = todayIn(homeZone, Date.now());
  const isoWeek = params.get("week") ?? isoWeekOf(today) ?? "";
  const isSession = isSessionMode(params);
  const screen = useWeekScreen(isoWeek);
  const areas = useAreas();
  const session = useWeeklySession(isoWeek, isSession);
  const days = screen.status === "ready" ? screen.days : [];
  const interaction = useWeekScreenInteraction({
    isoWeek,
    days,
    view: screen.status === "ready" ? screen.view : null,
    today,
    visibleHours: screen.status === "ready" ? screen.visibleHours : FALLBACK_VISIBLE_HOURS,
  });
  const words = useWeekWords({ screen, interaction, homeZone });

  /* THE MODE DECLARES ITSELF TO THE CLIENT, and clears on the way out. An effect rather than a call in the render, so a
   * reader who leaves the session stops marking their mutations even when they leave by pressing the browser's back
   * button: the cleanup runs on unmount and on every change of the mode. */
  useEffect(() => {
    setSessionModeOpen(isSession);
    return () => {
      setSessionModeOpen(false);
    };
  }, [isSession]);

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
          onSolveNow={interaction.onResolveNow}
          reason={screen.reason}
          setupHref={SETUP_HREF}
          statement={screen.facts.statement}
        />
      </RouteBand>
    );
  }

  const dates = days.map((day) => day.date);

  /* THE MODE IS A BRANCH OF THE READY SCREEN, so everything it draws from is the reading that reached here: a session
   * cannot open on a week with no plan and then render a grid, because the empty state above already answered.
   *
   * THE MODE'S OWN PENDING AND FAILED STATES TAKE THE MODE'S HEADER, not the screen's band. `RouteBand`'s title is
   * serif, which is the type reserved for a destination, so answering the session's own read inside one would claim it
   * for the second the payload is in flight. The header states no range yet, because the week has not been read. */
  if (isSession && session !== null) {
    if (session.status !== "ready") {
      return (
        <section aria-label="Weekly session">
          <SessionHeader isoWeek={isoWeek} range={null} />
          <div className="px-3.75 py-3.25">
            {session.status === "loading" ? (
              <PendingState
                title="Reading this week's session"
                detail="Last week's figures, everything raised since, and what this week can hold."
              />
            ) : (
              <ErrorState title="The session was not read" detail={session.problem.detail} />
            )}
          </div>
        </section>
      );
    }
    return (
      <SessionMode
        areas={areas.status === "ready" ? areas.data.areas : NO_AREAS}
        interaction={interaction}
        isoWeek={isoWeek}
        nowMs={Date.now()}
        screen={screen}
        session={session.data}
        words={words}
      />
    );
  }

  return (
    <RouteBand title="Week" sub={`${isoWeek} · ${weekRange(dates)}`}>
      <div className="flex flex-col gap-3.25">
        <WeekActions
          blockCount={screen.readings.blockCount}
          drawnHours={interaction.drawnHours}
          hasProposal={screen.view.proposal !== null}
          onApprove={interaction.onApprove}
          onPickHours={interaction.onPickHours}
          onResolveNow={interaction.onResolveNow}
          reportedLevels={interaction.reportedLevels}
          sessionHref={sessionPath(isoWeek)}
          unconfirmedDays={screen.readings.unconfirmedDays}
        />
        <SummaryStrip
          readings={{ ...screen.readings, planCurrency: interaction.operation.planCurrency }}
          verdict={words.stripVerdict}
        />
        <WeekHead
          concessions={words.concessions}
          conflicts={words.conflicts}
          notices={words.notices}
          onPropose={interaction.onPropose}
          verdict={words.verdict}
        />
        <WeekSurface interaction={interaction} nowMs={Date.now()} screen={screen} words={words} />
      </div>
    </RouteBand>
  );
}
