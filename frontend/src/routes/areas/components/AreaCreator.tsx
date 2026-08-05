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
 * THE TWO BUDGET FIELDS ARE PLAIN FIGURES AND NOT STEPPERS, and that is a correction. `NumberStepper` snaps
 * every commit to its measure's step and both of its measures count minutes, so with the ledger's five-minute
 * step a declared three-hour floor was POSTed as five and a 33% share as 35%. A weekly floor is a HARD solver
 * constraint and this panel is the only surface in the product that declares one, so a control that inflated
 * one by two thirds was the worst instance of that defect. Both figures are stored as `NUMERIC(5, 2)`, which
 * holds a floor to the hundredth of an hour, so no step is the right one: neither field has a grid.
 *
 * THE FIELDS HOLD THE READER'S OWN TEXT until they submit. A number would rewrite `3.` under the caret, and
 * the point of this change is that the figure written is the figure typed.
 *
 * A FLOOR AND A SHARE ARE BOTH OPTIONAL, because an Area with neither is a legitimate declaration: it holds
 * time and reports a zero target rather than an absent one. So a blank field is null rather than zero. */

import { useState } from "react";

import { Button, Input } from "../../../ui/primitives";
import { FormRow, Panel } from "../../../ui/layout";
import { parseFigure } from "../figures";
import type { AreaDeclarationBody, Ramp } from "../../../api/hooks/useAreas";
import type { Write } from "../../../api/hooks/useWrite";

/** What the reader has typed, before it is a declaration. */
interface Draft {
  readonly name: string;
  readonly floorHours: string;
  readonly budgetPercent: string;
}

const EMPTY: Draft = { name: "", floorHours: "", budgetPercent: "" };

export interface AreaCreatorProps {
  readonly ramp: Ramp;
  readonly write: Write<AreaDeclarationBody>;
}

/** The declaration a draft amounts to. A blank figure is null, which declares none. */
function bodyOf(draft: Draft): AreaDeclarationBody {
  return {
    name: draft.name,
    parentId: null,
    budgetPercent: parseFigure(draft.budgetPercent),
    floorHours: parseFigure(draft.floorHours),
  };
}

export function AreaCreator({ ramp, write }: AreaCreatorProps) {
  const [draft, setDraft] = useState<Draft>(EMPTY);

  const submit = async () => {
    if (await write.submit(bodyOf(draft))) setDraft(EMPTY);
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
          hint="A weekly minimum in hours the solver treats as a constraint, up to 168. Blank declares none."
        >
          {(field) => (
            <Input
              id={field.id}
              describedBy={field.describedBy}
              measure="figure"
              value={draft.floorHours}
              onValueChange={(floorHours) => setDraft({ ...draft, floorHours })}
              label="Weekly floor in hours"
            />
          )}
        </FormRow>

        <FormRow
          label="Share of remainder"
          hint="A percentage of the discretionary time the floors leave. Shares past 100 in total are reported, never refused."
        >
          {(field) => (
            <Input
              id={field.id}
              describedBy={field.describedBy}
              measure="figure"
              value={draft.budgetPercent}
              onValueChange={(budgetPercent) => setDraft({ ...draft, budgetPercent })}
              label="Share of the remainder, as a percentage"
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
