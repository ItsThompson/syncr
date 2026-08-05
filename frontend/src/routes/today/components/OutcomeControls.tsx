/* The three exceptions a reader can record on one row, and the way back to presumed.
 *
 * THE KEY HINT IS ON THE CONTROL, so the bracketed keystroke and the button that does the same thing are
 * one idea in one place. The keys are bound by the route, on the row a reader has focused, which is what
 * makes the whole ledger answerable without a pointer.
 *
 * THE CONTROLS ARE NAMED BY THE GROUP RATHER THAN EACH BY THE ROW. Ten rows of `skip` are ambiguous to a
 * screen reader, and putting the block's title into each button's own label would leave the visible text
 * outside its accessible name. A named group answers "which row" once, where a reader meets it.
 *
 * THERE IS NO `completed` CONTROL, and its absence is the product's whole premise: every block is presumed
 * complete with no user action, so a control asserting it would be a keystroke for the case that already
 * needs none. `presumed` is offered only where an exception has been recorded, because that is a
 * correction rather than an assertion. */

import { Button } from "../../../ui/primitives";
import { KeyHint } from "../../../ui/domain";
import { stateOf, type DayRow } from "../../../api/hooks/useDay";
import type { RowActions } from "../types";

export interface OutcomeControlsProps {
  readonly row: DayRow;
  readonly actions: RowActions;
}

export function OutcomeControls({ row, actions }: OutcomeControlsProps) {
  return (
    <fieldset className="flex items-center gap-2" aria-label={`outcome for ${row.title}`}>
      <Button rank="quiet" size="sm" onClick={() => actions.onSkip(row)}>
        skip <KeyHint keys="x" />
      </Button>
      <Button rank="quiet" size="sm" onClick={() => actions.onPartial(row)}>
        partial <KeyHint keys="Shift+X" />
      </Button>
      <Button rank="quiet" size="sm" onClick={() => actions.onMoved(row)}>
        moved <KeyHint keys="m" />
      </Button>
      {stateOf(row) === "presumed" ? null : (
        <Button rank="quiet" size="sm" onClick={() => actions.onPresume(row)}>
          presumed
        </Button>
      )}
    </fieldset>
  );
}
