/* The one calendar syncr writes to, what it does to it, and how far ahead.
 *
 * THE DESTRUCTIVE BEHAVIOUR IS THE API'S OWN SENTENCE, not this screen's copy. `writeTarget.statement` exists so
 * that whatever renders the write target renders the words, and a second surface cannot forget to say them: the
 * plan is reconciled destructively, and an event edited in a calendar client inside the horizon is overwritten.
 * That is the most consequential fact on this screen and it is part of the read model for exactly that reason.
 *
 * EXACTLY ONE CALENDAR HOLDS THE ROLE. Designating a second is a stated 409 rather than a silent handover, so the
 * control offers every other source and renders the refusal when the api will not make the change. Whether a
 * source acting as an anchor source may take the role is the api's rule to state, not this screen's to predict:
 * guessing it here would mean two definitions of one constraint, and the one on this side would be the wrong one
 * the day the other changed.
 *
 * THE HORIZON IS DAYS AND DEFAULTS TO FOURTEEN. It is a text field rather than the kit's stepper because the
 * stepper steps by the quarter hour: it is a control for a duration on the snap grid, and a count of days is
 * neither. */

import { useState } from "react";

import { EmptyState } from "../../../ui/domain";
import { FormRow, Panel } from "../../../ui/layout";
import { Button, Input, Select } from "../../../ui/primitives";
import { DefinitionRow } from "./DefinitionRow";
import { Refusal } from "./Refusal";
import { writeTargetOf } from "../writeTarget";
import type {
  CalendarSource,
  HorizonEdit,
  SourceReference,
} from "../../../api/hooks/useCalendarSources";
import type { Write } from "../../../api/hooks/useWrite";

/** The default the api applies, restated so the field's hint can name it. */
const DEFAULT_HORIZON_DAYS = 14;

export interface WriteTargetPanelProps {
  readonly sources: readonly CalendarSource[];
  readonly horizon: Write<HorizonEdit>;
  readonly role: Write<SourceReference>;
}

export function WriteTargetPanel({ sources, horizon, role }: WriteTargetPanelProps) {
  const target = writeTargetOf(sources);
  const candidates = sources.filter((source) => source.id !== target?.source.id);
  const [chosenId, setChosenId] = useState("");
  /* Null while the reader has not typed, so the field shows the stored figure; an empty string is a field they
     cleared, which has to stay empty rather than snapping back to the stored value under the cursor. */
  const [days, setDays] = useState<string | null>(null);

  if (target === null) {
    const designateId = chosenId === "" ? (candidates.at(0)?.id ?? "") : chosenId;
    return (
      <Panel title="Write target">
        <EmptyState
          title="No calendar holds the write-target role"
          detail={
            "Until one does, the plan stays inside syncr: it is still solved, still readable and still " +
            "editable, and nothing reaches your phone. Exactly one calendar may hold the role, and syncr " +
            "reconciles that one destructively."
          }
          action={
            candidates.length === 0 ? undefined : (
              <span className="flex flex-wrap items-end gap-3.25">
                <Select
                  label="Calendar to write the plan to"
                  value={designateId}
                  onValueChange={setChosenId}
                  options={candidates.map((source) => ({
                    value: source.id,
                    label: `${source.displayName} \u00b7 ${source.provider}`,
                  }))}
                />
                <Button onClick={() => void role.submit({ sourceId: designateId })}>
                  Designate the write target
                </Button>
              </span>
            )
          }
        />
        <Refusal problem={role.problem} />
      </Panel>
    );
  }

  const { source, reading } = target;

  return (
    <Panel title="Write target" headerEnd={<span>{reading.calendarName}</span>}>
      <dl className="flex flex-col">
        <DefinitionRow label="calendar">{reading.calendarName}</DefinitionRow>
        <DefinitionRow label="horizon" isFigure>{`${reading.horizonDays} days`}</DefinitionRow>
        <DefinitionRow label="reconciliation">{reading.reconciliation}</DefinitionRow>
      </dl>
      <p className="text-base text-ink-soft">{reading.statement}</p>
      <FormRow
        label="Horizon"
        hint={`How many days ahead the plan is written. Defaults to ${DEFAULT_HORIZON_DAYS}.`}
      >
        {(field) => (
          <span className="flex items-center gap-3.25">
            <Input
              id={field.id}
              describedBy={field.describedBy}
              measure="figure"
              value={days ?? String(reading.horizonDays)}
              onValueChange={setDays}
              isInvalid={horizon.problem !== null}
            />
            <Button
              rank="secondary"
              onClick={() =>
                void horizon.submit({
                  sourceId: source.id,
                  horizonDays: Number(days ?? reading.horizonDays),
                })
              }
            >
              Set the horizon
            </Button>
          </span>
        )}
      </FormRow>
      <Refusal problem={horizon.problem ?? role.problem} />
    </Panel>
  );
}
