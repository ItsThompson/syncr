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
 * BELOW --bp-wide THE PANEL CLOSES TO A RAIL rather than narrowing: a narrower panel cannot hold a reason and a narrower
 * grid cannot hold a title. The rail is a reserved column, so the grid's width does not change when the panel opens. */

import { WeekGrid } from "../../../ui/domain";
import { DetailPanel } from "./DetailPanel";
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

  return (
    <div className="flex gap-3.25">
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
          visibleHours={interaction.visibleHours}
        />
      </div>
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
  );
}
