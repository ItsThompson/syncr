/* The shapes this screen passes between its own parts.
 *
 * ONE OPEN FORM AT A TIME, AND IT CARRIES ITS DRAFT. Two states that always change together are one state:
 * which row is being edited, which of the two controls is open, and the figure the reader has typed into it
 * are meaningless apart, and a reader who opened the minutes stepper on one row and then the interval on
 * another would otherwise leave the first one open with a value nobody would send.
 *
 * THE ACTIONS ARRIVE AS ONE OBJECT rather than eight props threaded through two components. Every one of
 * them is the route's, because the route owns the writes; what a section and a row own is where the control
 * sits. */

import type { TimeRange } from "../../ui/primitives";
import type { DayRow } from "../../api/hooks/useDay";

/** Which of a day's two sections a row is rendered in, which is decided by whether the block has ended. */
export type LedgerSectionKind = "behind" | "ahead";

/** The minutes stepper, open on one row and prefilled with the planned duration. */
export interface PartialForm {
  readonly kind: "partial";
  readonly blockId: string;
  readonly minutes: number;
}

/** The interval control, open on one row and prefilled with the planned interval. */
export interface MovedForm {
  readonly kind: "moved";
  readonly blockId: string;
  readonly range: TimeRange;
}

export type OutcomeForm = PartialForm | MovedForm;

/** What a reader can do to one row, all of it owned by the route that holds the writes. */
export interface RowActions {
  readonly onSkip: (row: DayRow) => void;
  readonly onPartial: (row: DayRow) => void;
  readonly onMoved: (row: DayRow) => void;
  /** Back to presumed, which is the correction path for a row answered for by mistake. */
  readonly onPresume: (row: DayRow) => void;
  /** The open form's draft changed. */
  readonly onDraft: (form: OutcomeForm) => void;
  /** Record what the open form now holds. */
  readonly onRecord: () => void;
  readonly onCancel: () => void;
  /** The row a bare keystroke would act on, claimed by focusing anything inside it. */
  readonly onEnter: (row: DayRow) => void;
}
