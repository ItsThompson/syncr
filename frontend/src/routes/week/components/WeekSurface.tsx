/* THE GRID AND THE RAIL BESIDE IT, which the screen and the weekly session draw identically.
 *
 * ONE STATEMENT OF THE PAIR. The mode and the screen both render the seven columns and the detail panel's reserved
 * column, and two copies of that layout is how one of them comes to lose the rail: the grid's width would then change
 * when the panel opens on one surface and not on the other. The interaction is the same object on both, so the keyboard
 * map, the drag and the selection are one path rather than two that agree.
 *
 * THE DETAIL PANEL IS RENDERED ON BOTH, and that is what makes `Enter` mean something in the mode. The keyboard map is
 * the screen's own and `Enter` opens the panel; a surface that inherited the binding and drew no panel would leave a key
 * that silently does nothing.
 *
 * THE PANEL IS DRAWN FROM THE SELECTION AND THE OPEN STATE TOGETHER. A selection with the panel closed is a reader who
 * has chosen a block and not asked why it is there, which is the state the rail's control and `Enter` both answer; the
 * state travels down as `data-panel`, so a rule can select on it without a second copy of the condition.
 *
 * BELOW --bp-wide THE PANEL TAKES A ROW UNDER THE GRID rather than a column beside it: a narrower panel cannot hold a
 * reason and a narrower grid cannot hold a title, so the width the panel would have taken becomes height instead. The
 * rail stays the only column reserved beside the grid at that width, in both states, which is what keeps a day column at
 * the ledger's seventeen characters however the reader leaves the panel. Above the threshold the panel keeps the
 * reserved column it has always had and the surface is a row rather than a stack. */

import { NoticeCard, WeekGrid } from "../../../ui/domain";
import { DetailPanel } from "./DetailPanel";
import { DetailRail } from "./DetailRail";
import { columnLabel } from "../labels";
import type { WeekInteraction } from "../hooks/useWeekScreenInteraction";
import type { WeekWords } from "../hooks/useWeekWords";
import type { WeekScreenState } from "../useWeekScreen";

export interface WeekSurfaceProps {
  /** The screen's own ready reading, which the columns are cut from. */
  readonly screen: Extract<WeekScreenState, { status: "ready" }>;
  readonly interaction: WeekInteraction;
  readonly words: WeekWords;
  readonly nowMs: number;
}

export function WeekSurface({ screen, interaction, words, nowMs }: WeekSurfaceProps) {
  const dates = screen.days.map((day) => day.date);
  const dayNotices = screen.days.flatMap((day) => day.marks ?? []).map((mark) => mark.notice);

  return (
    <>
      {dayNotices.map((notice) => (
        <NoticeCard key={notice.id} notice={notice} />
      ))}
      <div
        className="flex flex-col gap-3.25 wide:flex-row"
        data-panel={interaction.isDetailOpen ? "open" : "closed"}
      >
        <div className="flex min-w-0 grow gap-3.25">
          <div className="min-w-0 grow">
            <WeekGrid
              days={screen.days}
              extent={screen.extent}
              interaction={{
                statesOf: interaction.statesOf,
                onSelect: interaction.onSelect,
                onDrop: interaction.onDrop,
                onBandActivate: interaction.onBandActivate,
              }}
              labels={dates.map(columnLabel)}
              nowMs={nowMs}
              onZoom={interaction.onZoom}
              visibleHours={interaction.proposedHours}
            />
          </div>
          <DetailRail
            isPanelOpen={interaction.isDetailOpen}
            onToggle={interaction.onToggleDetail}
          />
        </div>
        {words.detail === null || !interaction.isDetailOpen ? null : (
          <div className="wide:w-detail wide:shrink-0">
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
    </>
  );
}
