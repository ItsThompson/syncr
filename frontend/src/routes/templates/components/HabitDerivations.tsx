/* The two derivations, in the place a control for them would have been.
 *
 * EACH IS THE API'S OWN SENTENCE, RENDERED AS IT ARRIVES. The cursor's statement already names the variant, says
 * what put the cursor there, and says there is no control that sets it; the debt's states the figure against its
 * cap. Both are documented as the words an interface renders beside the value, so prefixing the variant or
 * appending a sentence of this screen's own would say each of those things twice.
 *
 * A HABIT THAT DOES NOT ROTATE HAS NO CURSOR, and this says so in words. There is no api sentence to defer to in
 * that case, because there is no cursor to have sent one: a fixed habit repeats one content and a queue habit
 * draws it from the backlog, so there is no rotation to be at a position in. */

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
            : habit.cursor.statement}
        </dd>
      </div>
      <div className="flex flex-col gap-1">
        <dt className="text-label tracking-label uppercase text-text-muted">Debt</dt>
        <dd className="text-sm text-ink">{habit.debt.statement}</dd>
      </div>
    </dl>
  );
}
