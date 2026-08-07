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
 * COMPOSITION ONLY. What is selected, what a key does, what a drop sends and what the last response said are
 * `useWeekScreenInteraction`'s; the reads are `useWeekScreen`'s; the words are `verdict.ts`'s and `reasons.ts`'s. What
 * is here is which surface each reading draws on, and in what order a reader meets them. */

import { useSearchParams } from "react-router";

import { useSettings } from "../api/hooks/useSettings";
import { todayIn } from "../lib/zonedInstant";
import { EmptyWeek, ErrorState, PendingState, SummaryStrip, WeekGrid } from "../ui/domain";
import { RouteBand } from "./RouteBand";
import { isoWeekOf } from "./today/isoWeek";
import { DetailPanel } from "./week/components/DetailPanel";
import { WeekActions } from "./week/components/WeekActions";
import { WeekHead } from "./week/components/WeekHead";
import { columnLabel, weekRange } from "./week/labels";
import { useWeekScreen } from "./week/useWeekScreen";
import { useWeekScreenInteraction } from "./week/hooks/useWeekScreenInteraction";
import { useWeekWords } from "./week/hooks/useWeekWords";

const SETUP_HREF = "/setup";
const SETTINGS_HREF = "/settings";
const FALLBACK_VISIBLE_HOURS = 12;

export function WeekRoute() {
  const [params] = useSearchParams();
  const settings = useSettings();
  const homeZone = settings.status === "ready" ? settings.data.homeZone : "UTC";
  const today = todayIn(homeZone, Date.now());
  const isoWeek = params.get("week") ?? isoWeekOf(today) ?? "";
  const screen = useWeekScreen(isoWeek);
  const days = screen.status === "ready" ? screen.days : [];
  const interaction = useWeekScreenInteraction({
    isoWeek,
    days,
    view: screen.status === "ready" ? screen.view : null,
    today,
    visibleHours: screen.status === "ready" ? screen.visibleHours : FALLBACK_VISIBLE_HOURS,
  });
  const words = useWeekWords({ screen, interaction, homeZone });

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

  return (
    <RouteBand title="Week" sub={`${isoWeek} · ${weekRange(dates)}`}>
      <div className="flex flex-col gap-3.25">
        <WeekActions
          blockCount={screen.readings.blockCount}
          currency={interaction.operation.planCurrency}
          hasProposal={screen.view.proposal !== null}
          onApprove={interaction.onApprove}
          onResolveNow={interaction.onResolveNow}
          visibleHours={interaction.visibleHours}
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
        <div className="flex gap-3.25">
          <div className="min-w-0 grow">
            <WeekGrid
              days={days}
              extent={screen.extent}
              interaction={{
                statesOf: interaction.statesOf,
                onSelect: interaction.onSelect,
                onDrop: interaction.onDrop,
                onBandActivate: interaction.onBandActivate,
              }}
              labels={dates.map(columnLabel)}
              nowMs={Date.now()}
              visibleHours={interaction.visibleHours}
            />
          </div>
          {/* BELOW --bp-wide THE PANEL CLOSES TO A RAIL rather than narrowing: a narrower panel cannot hold a reason
              and a narrower grid cannot hold a title. The rail is a reserved column, so the grid's width does not
              change when the panel opens. */}
          <div className="w-detail-closed shrink-0 border-l border-rule wide:hidden" />
          {words.detail === null ? null : (
            <div className="hidden w-detail shrink-0 wide:block">
              <DetailPanel
                actions={words.detail.actions}
                cost={words.detail.cost}
                definitionRows={words.detail.definitionRows}
                onClose={interaction.onCloseDetail}
                reasonRows={words.detail.reasonRows}
                title={words.detail.title}
              />
            </div>
          )}
        </div>
      </div>
    </RouteBand>
  );
}
