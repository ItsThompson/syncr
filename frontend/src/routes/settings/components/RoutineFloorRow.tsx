/* One routine's floor: the control, what the figure means for that routine, and its own refusal.
 *
 * THE WRITE IS THE ROW'S OWN, and that is why this is a component rather than a cell the panel draws.
 * `useRoutineEdit` is addressed to one routine, and a refusal belongs to the control that caused it: one instance
 * shared across the panel would report a refused floor under every other routine's field as well. The geometry
 * panel holds two instances for the same reason.
 *
 * THE REFUSAL GOES IN THE ROW'S MESSAGE SLOT, which is where the field's own description points. A typed figure
 * reaches the api unsnapped and unclamped by design, so this control can be refused by a bound the read it was
 * drawn from no longer states, and the sentence has to arrive attached to the field rather than beside it. The
 * slot already holds the negotiability hint and an error replaces it, so the row cannot state both at once.
 *
 * THE ROW IS NAMED BY THE ROUTINE AND ITS TARGET TIME, because two routines may share a title: a morning and an
 * evening `Shower` are both real, and two fields both named `Shower` leave a reader unable to say which one they
 * are in. */

import { useRoutineEdit } from "../../../api/hooks/useRoutines";
import { FormRow } from "../../../ui/layout";
import { NumberStepper } from "../../../ui/primitives";
import { statedClock, statedDuration } from "../format";
import { MIN_FLOOR_MINUTES, isElastic } from "../routineFloor";
import type { Routine } from "../../../api/hooks/useRoutines";

export interface RoutineFloorRowProps {
  readonly routine: Routine;
}

function statedNegotiability(routine: Routine): string {
  const target = statedDuration(routine.durationMinutes);
  return isElastic(routine)
    ? `Negotiable: the floor is below the target of ${target}, so the solver may propose spending the difference ` +
        "and may never spend it silently."
    : `Not negotiable: the floor equals the target of ${target}, so this routine is never shortened.`;
}

export function RoutineFloorRow({ routine }: RoutineFloorRowProps) {
  const write = useRoutineEdit(routine.id);

  return (
    <FormRow
      label={`${routine.title} \u00b7 ${statedClock(routine.targetTime)}`}
      hint={statedNegotiability(routine)}
      error={write.problem === null ? undefined : write.problem.detail}
    >
      {(field) => (
        <NumberStepper
          id={field.id}
          describedBy={field.describedBy}
          measure="duration"
          value={routine.minDurationMinutes}
          min={MIN_FLOOR_MINUTES}
          max={routine.durationMinutes}
          unit="min"
          isInvalid={write.problem !== null}
          onValueChange={(next) => void write.submit({ minDurationMinutes: next })}
        />
      )}
    </FormRow>
  );
}
