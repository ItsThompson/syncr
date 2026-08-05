/* Declaring an Area, and what the ramp says afterwards.
 *
 * NO COLOUR IS PICKED HERE AND NONE CAN BE. Creation deals the next step of a sealed twelve-step ramp, and
 * the request shape has no field for one, so this form has no control for one either. What the reader learns
 * is what they were dealt: the new Area appears in the table with its chip, and this panel states how many of
 * the twelve are in use.
 *
 * A THIRTEENTH TOP-LEVEL AREA IS A LEGITIMATE THING TO DECLARE AND A THIRTEENTH INK IS NOT A LEGITIMATE THING
 * TO INVENT, so past twelve the ramp repeats and this panel renders the api's own sentence saying that
 * identity now rests on the hatch and the Area name. THAT SENTENCE IS CURRENTLY OPTIMISTIC ABOUT THE HATCH:
 * the texture is a function of the ramp step, so a thirteenth Area takes the first Area's texture as well as
 * its ink, and the NAME is the whole of what separates the two. Ticket 1201 carries the decision between
 * surfacing the deal so the texture can vary and correcting the sentence. This screen shows every Area at
 * once, so it is where a reader meets the collision; the statement is rendered rather than paraphrased so
 * that whichever way 1201 resolves, this panel says what the product says.
 *
 * A FLOOR AND A SHARE ARE BOTH OPTIONAL, because an Area with neither is a legitimate declaration: it holds
 * time and reports a zero target rather than an absent one. */

import { useState } from "react";

import { Button, Input, NumberStepper } from "../../../ui/primitives";
import { FormRow, Panel } from "../../../ui/layout";
import type { AreaDeclarationBody, Ramp } from "../../../api/hooks/useAreas";
import type { Write } from "../../../api/hooks/useWrite";

const SHARE_MAX = 100;
const FLOOR_MAX_HOURS = 168;

const EMPTY: AreaDeclarationBody = {
  name: "",
  parentId: null,
  budgetPercent: null,
  floorHours: null,
};

export interface AreaCreatorProps {
  readonly ramp: Ramp;
  readonly write: Write<AreaDeclarationBody>;
}

export function AreaCreator({ ramp, write }: AreaCreatorProps) {
  const [draft, setDraft] = useState<AreaDeclarationBody>(EMPTY);

  const submit = async () => {
    if (await write.submit(draft)) setDraft(EMPTY);
  };

  return (
    <Panel
      title="Declare an Area"
      headerEnd={
        <span className="text-eyebrow">
          {ramp.pigmentsInUse} of {ramp.pigmentCount} pigments in use
        </span>
      }
      footer={ramp.statement === null ? undefined : <span>{ramp.statement}</span>}
    >
      <form
        className="flex flex-col gap-2"
        aria-label="Declaring an Area"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <FormRow
          label="Name"
          isRequired
          hint="Unique within your Areas. Past twelve the ramp repeats, so the name is what identifies one."
        >
          {(field) => (
            <Input
              id={field.id}
              describedBy={field.describedBy}
              value={draft.name}
              onValueChange={(name) => setDraft({ ...draft, name })}
              isRequired
              label="Area name"
            />
          )}
        </FormRow>

        <FormRow
          label="Floor / wk"
          hint="A weekly minimum the solver treats as a constraint. 0 declares none."
        >
          {(field) => (
            <NumberStepper
              id={field.id}
              describedBy={field.describedBy}
              value={draft.floorHours ?? 0}
              onValueChange={(hours) => setDraft({ ...draft, floorHours: hours || null })}
              measure="actual-minutes"
              min={0}
              max={FLOOR_MAX_HOURS}
              unit="hours"
              label="Weekly floor in hours"
            />
          )}
        </FormRow>

        <FormRow
          label="Share of remainder"
          hint="A share of the discretionary time the floors leave. Shares past 100 in total are reported, never refused."
        >
          {(field) => (
            <NumberStepper
              id={field.id}
              describedBy={field.describedBy}
              value={draft.budgetPercent ?? 0}
              onValueChange={(percent) => setDraft({ ...draft, budgetPercent: percent || null })}
              measure="actual-minutes"
              min={0}
              max={SHARE_MAX}
              unit="%"
              label="Share of the remainder"
            />
          )}
        </FormRow>

        {write.problem === null ? null : (
          <p role="alert" className="text-sm text-signal-oxide">
            {write.problem.detail}
          </p>
        )}

        <span>
          <Button type="submit">Declare it</Button>
        </span>
      </form>
    </Panel>
  );
}
