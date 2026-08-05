/* Authoring one Area's placement preference, in the cell the reader was already looking at.
 *
 * A PREFERENCE IS REPLACED WHOLLY. The api takes a `PUT` rather than a `PATCH` because a preference replaces
 * its Area's windows and ideal duration entire, so there is no merge rule to express and no field-by-field
 * edit to model: this form submits every field it holds, and a cleared one is null afterwards.
 *
 * THE DAILY CAP IS RENDERED ONLY FOR AN AREA. `owner` is a parameter rather than an assumption, and the cap
 * control does not exist for a habit or a task: a cap is a HARD constraint and an Area's alone, so an override
 * that could carry one would be an override that could relax one. The api refuses the field at the boundary;
 * this form does not offer it at all, which is the same rule one layer earlier.
 *
 * AN EMPTY WINDOW LIST IS A STATEMENT, NOT AN OMISSION. Removing the last window and saving declares that this
 * Area names no time of day, which is a real declaration: the strength then weighs nothing. That is why the
 * control stays available at one window rather than being disabled there.
 *
 * REMOVING THE DECLARATION IS A SEPARATE ACT from saving an empty one. `Remove the declaration` deletes the
 * Area's own preference so nothing is declared at all; saving with no window declares one that names no time.
 *
 * NOTHING HERE SPINS AND THERE IS NO SUBMITTING FLAG, because nothing in this product may spin: a flag whose
 * only use is drawing a spinner would have no reader. */

import { useId, useState } from "react";

import { Button, NumberStepper, Select, TimeRangeInput } from "../../../ui/primitives";
import { FormRow } from "../../../ui/layout";
import {
  bodyOf,
  draftOf,
  withAnotherWindow,
  withCap,
  withIdealDuration,
  withStrength,
  withWindow,
  withoutWindow,
} from "../preference";
import type {
  AreaPreferenceEdit,
  AreaPreferenceRemoval,
  Preference,
  PreferenceStrength,
} from "../../../api/hooks/usePreferences";
import type { Write } from "../../../api/hooks/useWrite";

/** Which kind of owner this form authors for. A daily cap exists on exactly one of the three. */
export type PreferenceOwnerKind = "area" | "habit" | "task";

const STRENGTHS = [
  { value: "soft", label: "soft" },
  { value: "strong", label: "strong" },
] as const;

/** The widest figures the api accepts, so a stepper cannot offer a value it would refuse. */
const CAP_MAX_MINUTES = 1440;
const IDEAL_MAX_MINUTES = 480;

export interface PreferenceEditorProps {
  readonly areaId: string;
  readonly areaName: string;
  readonly preference: Preference | undefined;
  /** An Area by default. A habit or a task gets no cap control at all. */
  readonly owner?: PreferenceOwnerKind | undefined;
  readonly onClose: () => void;
  readonly declare: Write<AreaPreferenceEdit>;
  readonly remove: Write<AreaPreferenceRemoval>;
}

export function PreferenceEditor({
  areaId,
  areaName,
  preference,
  owner = "area",
  onClose,
  declare,
  remove,
}: PreferenceEditorProps) {
  const scope = useId();
  const [draft, setDraft] = useState(() => draftOf(preference));
  const [added, setAdded] = useState(0);
  const refusal = declare.problem ?? remove.problem;

  const save = async () => {
    if (await declare.submit({ areaId, preference: bodyOf(draft) })) onClose();
  };
  const clear = async () => {
    if (await remove.submit({ areaId })) onClose();
  };
  const addWindow = () => {
    setDraft(withAnotherWindow(draft, `${scope}-added-${added}`));
    setAdded(added + 1);
  };

  return (
    <form
      className="flex flex-col gap-2"
      aria-label={`Placement preference for ${areaName}`}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      {draft.windows.map((window, index) => (
        <FormRow key={window.id} label={`Window ${index + 1}`}>
          {(field) => (
            <span className="flex items-center gap-2">
              <TimeRangeInput
                value={window}
                onValueChange={(next) => setDraft(withWindow(draft, window.id, next))}
                label={`Window ${index + 1}`}
                describedBy={field.describedBy}
              />
              <Button rank="quiet" onClick={() => setDraft(withoutWindow(draft, window.id))}>
                Remove
              </Button>
            </span>
          )}
        </FormRow>
      ))}

      <span>
        <Button rank="tertiary" onClick={addWindow}>
          Add a window
        </Button>
      </span>

      <FormRow
        label="Strength"
        hint="Both are costs the solver trades off. Neither can leave a block unscheduled, and there is no hard."
      >
        {(field) => (
          <Select
            id={field.id}
            describedBy={field.describedBy}
            value={draft.strength}
            onValueChange={(next) => setDraft(withStrength(draft, next as PreferenceStrength))}
            options={STRENGTHS}
          />
        )}
      </FormRow>

      <FormRow
        label="Ideal session"
        hint="A split shorter than this is placed and charged to fragmentation, never refused."
      >
        {(field) => (
          <NumberStepper
            id={field.id}
            describedBy={field.describedBy}
            value={draft.preferredDurationMinutes ?? 0}
            onValueChange={(next) => setDraft(withIdealDuration(draft, next === 0 ? null : next))}
            measure="duration"
            min={0}
            max={IDEAL_MAX_MINUTES}
            unit="min, 0 for none"
          />
        )}
      </FormRow>

      {owner === "area" ? (
        <FormRow
          label="Daily cap"
          hint="A hard constraint, and an Area's alone: an override cannot carry one, so it can never relax this."
        >
          {(field) => (
            <NumberStepper
              id={field.id}
              describedBy={field.describedBy}
              value={draft.maxPerDayMinutes ?? 0}
              onValueChange={(next) => setDraft(withCap(draft, next === 0 ? null : next))}
              measure="duration"
              min={0}
              max={CAP_MAX_MINUTES}
              unit="min, 0 for none"
            />
          )}
        </FormRow>
      ) : null}

      {refusal === null ? null : (
        <p role="alert" className="text-sm text-signal-oxide">
          {refusal.detail}
        </p>
      )}

      <span className="flex items-center gap-2">
        <Button type="submit">Save</Button>
        <Button rank="secondary" onClick={onClose}>
          Cancel
        </Button>
        {preference?.declared === null || preference?.declared === undefined ? null : (
          <Button rank="quiet" onClick={() => void clear()}>
            Remove the declaration
          </Button>
        )}
      </span>
    </form>
  );
}
