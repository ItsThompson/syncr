/* THE WEEKLY SESSION, AS A MODE OF THE WEEK SCREEN.
 *
 * NO SERIF TITLE. A page title is serif and a mode header is not, because a mode is not a destination and so does not
 * claim the type reserved for one. `SessionHeader` holds that rule; nothing here draws a heading.
 *
 * THE MODE IS REACHABLE BY URL, so it survives a reload and can be linked. That is `?mode=session` on the Week screen's
 * own route, which is why this is a branch of `WeekRoute` rather than a route of its own: a second route would be a
 * second destination, and the whole point is that the session is a way of USING the week.
 *
 * THE GRID, THE DETAIL PANEL, THE PIN PATH, THE VERDICT PANEL AND THE APPROVE ACTION ARE THE SCREEN'S OWN, reused rather
 * than restated. Editing inside the session pins through the same write, the solver reflows the remainder, and the
 * verdict updates live because the panel is drawn from the same reading the screen draws it from. A second panel fed by
 * this mode's own payload would disagree with the screen's the moment a solve landed between two reads, and a second
 * approve control would be a second way to commit a week.
 *
 * WHAT THE MODE ADDS is the retrospective, the raised items, and the promotion candidates. None of the three appears
 * outside the mode: `US-REV-02`'s escalation and an available promotion are both "in weekly-session mode only" in
 * section 16's notice-volume table.
 *
 * A WEEK THAT MOVED ON WHILE THE SESSION WAS OPEN SAYS SO. The payload states the input version it was composed
 * against, and a pin made inside the session bumps the week's own: the plan and the verdict re-read on the spot and the
 * raises do not, so the reader is told which half is older rather than left to assume both are current. */

import { RaisedPanel, SummaryStrip, VerdictPanel } from "../../../ui/domain";
import { weekRange } from "../labels";
import { WeekActions } from "../components/WeekActions";
import { WeekSurface } from "../components/WeekSurface";
import { raisesOf } from "./raises";
import { PromotionPanel } from "./components/PromotionPanel";
import { RetroPanel } from "./components/RetroPanel";
import { SessionHeader } from "./components/SessionHeader";
import { usePromotionAccept, usePromotionDecline } from "../../../api/hooks/usePromotions";
import type { Area } from "../../../api/hooks/useAreas";
import type { WeeklySession } from "../../../api/hooks/useWeeklySession";
import type { WeekInteraction } from "../hooks/useWeekScreenInteraction";
import type { WeekWords } from "../hooks/useWeekWords";
import type { WeekScreenState } from "../useWeekScreen";

const MOVED_ON =
  "The week has changed since these raises were computed, so the plan and the verdict above are " +
  "newer than the list below. Re-open the session to recompute it.";

export interface SessionModeProps {
  readonly isoWeek: string;
  readonly session: WeeklySession;
  /** The screen's own ready reading, which the grid, the strip and the panel are drawn from. */
  readonly screen: Extract<WeekScreenState, { status: "ready" }>;
  readonly interaction: WeekInteraction;
  readonly words: WeekWords;
  readonly areas: readonly Area[];
  readonly nowMs: number;
}

export function SessionMode({
  isoWeek,
  session,
  screen,
  interaction,
  words,
  areas,
  nowMs,
}: SessionModeProps) {
  const hasMovedOn = session.inputVersion !== screen.view.inputVersion;
  /* Both answers belong to the week this session plans: accepting bumps its input version through the day shape it
   * edits, and declining changes what this payload raises. So both are keyed on it rather than on today. */
  const accept = usePromotionAccept(isoWeek);
  const decline = usePromotionDecline(isoWeek);

  return (
    <section aria-label="Weekly session">
      <SessionHeader isoWeek={isoWeek} range={weekRange(screen.days.map((day) => day.date))} />
      <div className="flex flex-col gap-3.25 px-3.75 py-3.25">
        <WeekActions
          blockCount={screen.readings.blockCount}
          hasProposal={screen.view.proposal !== null}
          onApprove={interaction.onApprove}
          onResolveNow={interaction.onResolveNow}
          sessionHref={null}
          visibleHours={interaction.visibleHours}
        />
        <SummaryStrip
          readings={{ ...screen.readings, planCurrency: interaction.operation.planCurrency }}
          verdict={words.stripVerdict}
        />
        {words.verdict === null ? null : (
          <VerdictPanel
            concessions={words.concessions}
            onPropose={interaction.onPropose}
            verdict={words.verdict}
          />
        )}
        <WeekSurface interaction={interaction} nowMs={nowMs} screen={screen} words={words} />
        {hasMovedOn ? <p className="text-sm text-text-muted">{MOVED_ON}</p> : null}
        <RaisedPanel raises={raisesOf(session.raised)} />
        <PromotionPanel
          accept={accept}
          candidates={session.promotions}
          decline={decline}
          statement={session.promotionStatement}
        />
        <RetroPanel areas={areas} retro={session.retro} />
      </div>
    </section>
  );
}
