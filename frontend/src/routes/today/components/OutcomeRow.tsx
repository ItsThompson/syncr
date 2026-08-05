/* One ledger row: what it is, what the log says about it, and whatever the reader can do about that.
 *
 * THE ROW CLAIMS THE KEYBOARD BY BEING FOCUSED, AND RELEASES IT WHEN FOCUS LEAVES. `x`, `Shift+X` and `m`
 * are bare keys bound by the route, and the row they act on is the one holding focus, which a reader reaches
 * by tabbing to its controls. Nothing here invents a second focus channel: the controls are real buttons and
 * the ring is the kit's. The release is guarded on containment, because focus moving from one control of this
 * row to another has not left the row.
 *
 * FOCUS FOLLOWS THE FORM A KEYSTROKE OPENS, AND COMES BACK WHEN IT CLOSES. The control that held focus
 * unmounts when the form replaces it, so without the handoff focus falls to the document and the figure the
 * keystroke just asked for could not be typed. `Shift+X` then a step then Enter is the whole of a partial
 * because of it.
 *
 * THE PLANNED FIGURES STAY IN THEIR COLUMNS. A `moved` row shows the planned interval in the time column
 * and the actual one in the outcome column, and a `partial` row shows the planned minutes in the duration
 * column and both figures in the outcome column, which is what "shows both" means on a row this dense.
 *
 * A REFUSAL RENDERS UNDER THE ROW rather than inside it. Volume one is inline at the thing it concerns, and
 * a notice in the outcome column would push the controls off a row whose whole point is that they sit at
 * one offset. It is a sibling of the row, so the run of rows keeps its own hairlines. */

import { useEffect, useRef, type FocusEvent } from "react";

import { LedgerRow, NoticeCard, type LedgerRowArea } from "../../../ui/domain";
import type { Notice } from "../../../ui/domain";
import type { DayRow } from "../../../api/hooks/useDay";
import { clockRange, minutesRead, stateReading } from "../labels";
import { MovedInterval } from "./MovedInterval";
import { PartialMinutes } from "./PartialMinutes";
import { OutcomeControls } from "./OutcomeControls";
import type { LedgerSectionKind, OutcomeForm, RowActions } from "../types";

export interface OutcomeRowProps {
  readonly row: DayRow;
  readonly zone: string;
  readonly section: LedgerSectionKind;
  /** Absent where the block carries no Area, and where the Area it names is gone. */
  readonly area?: LedgerRowArea | undefined;
  /** The form open on THIS row, or null when none is. */
  readonly form: OutcomeForm | null;
  /** The refusal that belongs to THIS row, or null when none does. */
  readonly refusal: Notice | null;
  readonly actions: RowActions;
}

export function OutcomeRow({ row, zone, section, area, form, refusal, actions }: OutcomeRowProps) {
  /* Which side of the swap the row is on, so the controls know to take focus back from a form that closed
     rather than on every render of the ledger. */
  const wasOpen = useRef(false);
  const isReturning = wasOpen.current && form === null;
  useEffect(() => {
    wasOpen.current = form !== null;
  });

  /* `relatedTarget` is the element focus is moving TO, and null when it is moving to nothing. Either way,
     focus has left this row unless the destination is inside it. */
  const onBlur = (event: FocusEvent<HTMLElement>): void => {
    if (!event.currentTarget.contains(event.relatedTarget)) actions.onLeave();
  };

  return (
    <>
      <LedgerRow
        timeRange={clockRange(row.interval, zone)}
        duration={minutesRead(row.durationMinutes)}
        title={row.title}
        area={area}
      >
        {/* Focus reaches this span from the controls inside it, which is how the row becomes the one a
            bare keystroke acts on. */}
        <span
          className="flex items-center gap-2"
          onFocus={() => actions.onEnter(row)}
          onBlur={onBlur}
        >
          <span className="text-eyebrow text-text-muted">{stateReading(row, section, zone)}</span>
          {form === null ? (
            <OutcomeControls row={row} actions={actions} shouldTakeFocus={isReturning} />
          ) : null}
          {form?.kind === "partial" ? (
            <PartialMinutes row={row} form={form} actions={actions} />
          ) : null}
          {form?.kind === "moved" ? (
            <MovedInterval row={row} form={form} actions={actions} />
          ) : null}
        </span>
      </LedgerRow>
      {refusal === null ? null : <NoticeCard notice={refusal} />}
    </>
  );
}
