/* A floor per routine: the least each one may be compressed to, and what setting one does.
 *
 * ONE HOME FOR THE VALUE. Each control edits `minDurationMinutes` on its own routine through
 * `PATCH /api/v1/routines/{id}`. They are rendered here because that is where a reader looks for them, and
 * `SettingsPatchRequest` does not carry the field and rejects an unknown member, so there is no second place one
 * could be written to by accident. The solver reads them from the domain.
 *
 * A FLOOR BELOW THE TARGET IS WHAT MAKES A ROUTINE NEGOTIABLE, and that is the whole of it: no routine is singled
 * out here and none is special. `reduce_routine` is offered as a tradeoff for exactly the routines whose floor is
 * below their target, and for those the solver may PROPOSE spending the difference and may never spend it silently.
 * Every row says which it is, because a floor set without understanding it is a floor set against the reader's
 * intent.
 *
 * WHAT THE DENOMINATOR SUBTRACTS IS THE DURATION, NOT THIS FLOOR. A routine's duration is the frame, and the frame
 * is the first of the budget denominator's four subtrahends: `WeekOccupancy.frame` in
 * `syncr_api/budgets/occupancy.py` is the set a routine's time lands in, and `WeekOccupancyReader` is the half that
 * applies it, in that it is what supplies that set to the subtraction. The set carries effective durations rather
 * than targets, so a floor below the target is the only way that subtraction can ever come out lower; nothing on
 * this panel moves a target. */

import { EmptyState } from "../../../ui/domain";
import { Panel } from "../../../ui/layout";
import { RoutineFloorRow } from "./RoutineFloorRow";
import type { Routine } from "../../../api/hooks/useRoutines";

export interface RoutineFloorsPanelProps {
  readonly routines: readonly Routine[];
}

export function RoutineFloorsPanel({ routines }: RoutineFloorsPanelProps) {
  if (routines.length === 0) {
    return (
      <Panel title="Routine floors">
        <EmptyState
          title="No routines are declared"
          detail={
            "A floor is the minimum duration of a routine, so there is nothing to set until a routine exists. " +
            "Every other setting on this screen is unaffected, and a week still solves: with no routine the " +
            "whole day is discretionary and there is no frame for the solver to spend."
          }
        />
      </Panel>
    );
  }

  return (
    <Panel title="Routine floors" headerEnd={<span>{routines.length}</span>}>
      <p className="text-base text-ink-soft">
        {"A floor is the least of a routine the solver may ever propose. Equal to the target duration, which is " +
          "every routine's default, the routine is never shortened. Below it, the difference is negotiable: the " +
          "solver may offer to spend it and may never spend it silently."}
      </p>
      {routines.map((routine) => (
        <RoutineFloorRow key={routine.id} routine={routine} />
      ))}
    </Panel>
  );
}
