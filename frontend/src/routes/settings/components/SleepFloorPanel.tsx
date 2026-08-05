/* The sleep floor: a labelled shortcut to one field on one routine, and not a settings value.
 *
 * ONE HOME FOR THE VALUE. This control edits `minDurationMinutes` on the sleep routine through
 * `PATCH /api/v1/routines/{id}`. It is rendered here because that is where a reader looks for it, and
 * `SettingsPatchRequest` does not carry the field and rejects an unknown member, so there is no second place it
 * could be written to by accident. The solver reads it from the domain.
 *
 * IT IS THE ONE NEGOTIABLE ROUTINE, WHICH IS WHY IT HAS A CONTROL AT ALL. A routine whose floor equals its target
 * is never shortened, and that equality is the default for every routine. Lowering sleep's floor below its target
 * is what makes `reduce_routine` available as a tradeoff: the solver may then PROPOSE spending sleep and may never
 * spend it silently. The panel says exactly that, because a floor set without understanding it is a floor set
 * against the reader's intent.
 *
 * THE STEPPER IS THE DURATION VARIANT, so it steps by the quarter hour like every other span in this product. Its
 * ceiling is the routine's target duration, which is the api's own bound: a floor above the target would make the
 * target meaningless. */

import { EmptyState } from "../../../ui/domain";
import { FormRow, Panel } from "../../../ui/layout";
import { NumberStepper } from "../../../ui/primitives";
import { statedDuration } from "../format";
import { MIN_FLOOR_MINUTES, isElastic } from "../sleepFloor";
import { DefinitionRow } from "./DefinitionRow";
import { Refusal } from "./Refusal";
import type { Routine, RoutinePatchBody } from "../../../api/hooks/useRoutines";
import type { Write } from "../../../api/hooks/useWrite";

export interface SleepFloorPanelProps {
  /** The sleep routine, or null when the tenant has declared no routine titled `Sleep`. */
  readonly routine: Routine | null;
  readonly write: Write<RoutinePatchBody>;
}

export function SleepFloorPanel({ routine, write }: SleepFloorPanelProps) {
  if (routine === null) {
    return (
      <Panel title="Sleep floor">
        <EmptyState
          title="No routine named Sleep is declared"
          detail={
            "The sleep floor is the minimum duration on the sleep routine, so there is nothing to set until " +
            "that routine exists. Every other setting on this screen is unaffected, and a week still solves: " +
            "without a sleep routine there is simply no sleep for the solver to spend."
          }
        />
      </Panel>
    );
  }

  return (
    <Panel
      title="Sleep floor"
      headerEnd={<span>{statedDuration(routine.minDurationMinutes)}</span>}
    >
      <dl className="flex flex-col">
        <DefinitionRow label="target" isFigure>
          {statedDuration(routine.durationMinutes)}
        </DefinitionRow>
        <DefinitionRow label="floor" isFigure>
          {statedDuration(routine.minDurationMinutes)}
        </DefinitionRow>
        <DefinitionRow label="negotiable">
          {isElastic(routine)
            ? "yes, between the floor and the target"
            : "no, the floor equals the target"}
        </DefinitionRow>
      </dl>
      <FormRow
        label="Sleep floor"
        hint={
          `The least sleep the solver may ever propose, out of a target of ` +
          `${statedDuration(routine.durationMinutes)}. Below the target, the solver may PROPOSE spending the ` +
          "difference and may never spend it silently. Equal to the target, sleep is never shortened."
        }
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
      <Refusal problem={write.problem} />
    </Panel>
  );
}
