/* Visible hours and the day bounds, and what each one does to the Week grid.
 *
 * THE SCREEN STATES THE EFFECT RATHER THAN LEAVING IT TO BE DISCOVERED. Two settings here drive the geometry of
 * another screen, which is the one case on Settings where a reader cannot see what they changed. So each control
 * says what the Week grid will do: how much of a day is on screen at once, and that the bounds are where the axis
 * STARTS rather than where it stops.
 *
 * DAY BOUNDS ARE A DEFAULT EXTENT AND NEVER A CROP. The axis is the union of these bounds and the bounding
 * interval of every block in the visible week, so a block outside them widens the axis rather than being hidden.
 * A block hidden by an axis is a scheduling error the reader cannot see, which is why the rule exists and why the
 * panel says it in words rather than implying it by calling the field a range.
 *
 * A LEVEL PAST THE DISPLAY'S CAP IS OFFERED AS UNAVAILABLE. The range, the cap and the per-level reason are the
 * grid's own, in `ui/domain/week-grid/zoom.ts`; what this screen supplies is the height, because it has no grid to
 * measure. See `../geometry.ts`.
 *
 * TWO WRITE INSTANCES, ONE PER CONTROL. A write hook holds the last refusal, and a refusal belongs to the control
 * that caused it: one instance would mark the day bounds invalid because a visible-hours change was refused. Both
 * invalidate the same key by name, so the reading stays one reading.
 *
 * BOTH TAKE EFFECT ON THE NEXT RENDER WITH NO RELOAD. The write invalidates the settings key by name, the reading
 * on this panel is the same resource the Week grid derives from, and one refetch redraws both. There is nothing
 * to reload and no second copy of the value to keep in step.
 *
 * A DAY BOUND IS A WALL TIME AND CARRIES NO OFFSET. The control is the kit's time input, whose value is `HH:MM`,
 * so what reaches the api names no zone: the zone comes from the day being rendered. The api is where that rule
 * is enforced for every writer, and `tickets/1150` carries closing the gap on this endpoint. */

import { useState } from "react";

import { FormRow, Panel } from "../../../ui/layout";
import { Button, Select, TimeRangeInput, snapClock, type TimeRange } from "../../../ui/primitives";
import { zoomLevels } from "../../../ui/domain/week-grid/zoom";
import { capStatement } from "../geometry";
import type { Settings, SettingsPatchBody } from "../../../api/hooks/useSettings";
import type { Write } from "../../../api/hooks/useWrite";

export interface GeometryPanelProps {
  readonly settings: Settings;
  /** The grid height this display would give the Week screen, which is what caps the zoom range. */
  readonly gridHeightPx: number;
  /** Writes the visible hours. Its own instance, so its refusal cannot appear under the day bounds. */
  readonly hoursPatch: Write<SettingsPatchBody>;
  readonly boundsPatch: Write<SettingsPatchBody>;
}

/** `07:00:00` from the api is a wall time; the control's value is `HH:MM`. */
function asClock(wallTime: string): string {
  return wallTime.slice(0, 5);
}

export function GeometryPanel({
  settings,
  gridHeightPx,
  hoursPatch,
  boundsPatch,
}: GeometryPanelProps) {
  const [bounds, setBounds] = useState<TimeRange | null>(null);
  const shown = bounds ?? { start: asClock(settings.dayStart), end: asClock(settings.dayEnd) };

  const levels = zoomLevels(gridHeightPx);

  const applyBounds = async () => {
    /* Snapped on the way out, so a bound lands on the same quarter-hour grid every start and end in this
       product lands on. The api takes a wall time with no offset and no seconds, which is what `HH:MM` is. */
    const dayStart = snapClock(shown.start);
    const dayEnd = snapClock(shown.end);
    if (dayStart === null || dayEnd === null) return;
    const applied = await boundsPatch.submit({ dayStart, dayEnd });
    if (applied) setBounds(null);
  };

  return (
    <Panel title="Grid geometry">
      <FormRow
        label="Visible hours"
        hint={`How much of a day the Week grid shows at once. ${capStatement(gridHeightPx)}`}
        error={hoursPatch.problem === null ? undefined : hoursPatch.problem.detail}
      >
        {(field) => (
          <Select
            id={field.id}
            describedBy={field.describedBy}
            value={String(settings.visibleHours)}
            onValueChange={(next) => void hoursPatch.submit({ visibleHours: Number(next) })}
            isInvalid={hoursPatch.problem !== null}
            options={levels.map((level) => ({
              value: String(level.hours),
              label:
                level.unavailableReason === null
                  ? `${level.hours} hours`
                  : `${level.hours} hours \u00b7 unavailable on this display`,
              isDisabled: !level.isAvailable,
            }))}
          />
        )}
      </FormRow>
      <FormRow
        label="Day bounds"
        hint={
          "Where the Week grid's axis STARTS by default, never where it stops: a block outside these hours " +
          "widens the axis rather than being hidden. Wall time, in whichever zone is active on the day."
        }
        error={boundsPatch.problem === null ? undefined : boundsPatch.problem.detail}
        isGroup
      >
        {(field) => (
          <span className="flex flex-wrap items-center gap-3.25">
            <TimeRangeInput
              labelledBy={field.labelledBy}
              describedBy={field.describedBy}
              value={shown}
              onValueChange={setBounds}
              isInvalid={boundsPatch.problem !== null}
            />
            <Button rank="secondary" onClick={() => void applyBounds()}>
              Set the day bounds
            </Button>
          </span>
        )}
      </FormRow>
      <p className="text-base text-ink-soft">
        {`At ${settings.visibleHours} hours the grid shows ${settings.visibleHours} of the day's ` +
          `hours at a time and scrolls to the rest. The axis opens on ${asClock(settings.dayStart)} to ` +
          `${asClock(settings.dayEnd)} and expands to contain every block in the week being read. Both ` +
          "take effect on the next render, with no reload."}
      </p>
    </Panel>
  );
}
