/* The two derivations, in the place a control for them would have been.
 *
 * A DERIVATION IS RENDERED WITH ITS PROVENANCE OR NOT AT ALL. The cursor's own sentence says why it is where it
 * is: a variant became next because the one before it was confirmed complete, so the cursor is a projection of
 * the outcome log rather than a field. Rendering the value without the sentence would make it look like state
 * somebody set.
 *
 * A HABIT THAT DOES NOT ROTATE HAS NO CURSOR, and this says so in words. A fixed habit repeats one content and
 * a queue habit draws it from the backlog, so there is no rotation to be at a position in. */

import type { Habit } from "../../../api/hooks/useHabits";

export interface HabitDerivationsProps {
  readonly habit: Habit;
}

export function HabitDerivations({ habit }: HabitDerivationsProps) {
  return (
    <dl className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        <dt className="text-label tracking-label uppercase text-text-muted">Rotation cursor</dt>
        <dd className="text-sm text-ink">
          {habit.cursor === null
            ? `A ${habit.bindingSource} habit has no rotation, so it has no cursor. There is no control that sets one.`
            : `${habit.cursor.variant} \u00B7 ${habit.cursor.statement} There is no control that sets one: correct the day on Today and this re-derives.`}
        </dd>
      </div>
      <div className="flex flex-col gap-1">
        <dt className="text-label tracking-label uppercase text-text-muted">Debt</dt>
        <dd className="text-sm text-ink">{habit.debt.statement}</dd>
      </div>
    </dl>
  );
}
