/* Declaring one entry on the selected day shape.
 *
 * THE KIND CHOOSES THE CONTROLS, which is what makes the pairing rule visible instead of discoverable. A
 * concrete entry offers the routine or habit it names and no Area; a slot offers the Area and has nowhere to
 * put a binding. So a body that names both, or neither, cannot be assembled here at all, and the submit is
 * refused while the kind's own member is still unchosen.
 *
 * WHAT IS NOT CHECKED HERE is every bound and every relation: the api holds those, and its refusal arrives
 * naming the member to change. That refusal is rendered inline, in amber, at the top of this panel.
 *
 * THE DRAFT SURVIVES A SUCCESSFUL DECLARATION. A day shape is filled in one sitting and its entries differ by
 * a target time and a duration far more often than by kind, so clearing the form after each entry would make
 * the second one as much work as the first. */

import { useState } from "react";

import { NoticeCard } from "../../../ui/domain";
import { FormRow } from "../../../ui/layout";
import { Button, Radio, Select, TimeInput } from "../../../ui/primitives";
import { bindingFrom, bindingValue } from "../bindings";
import { EMPTY_ENTRY_DRAFT, entryProposalFrom, type EntryDraft } from "../entryDraft";
import { messageFor, rejectionNotice } from "../rejection";
import { MinutesRow } from "./MinutesRow";
import type { Area } from "../../../api/hooks/useAreas";
import type { Habit } from "../../../api/hooks/useHabits";
import type { Routine } from "../../../api/hooks/useRoutines";
import type { EntryBody } from "../../../api/hooks/useTemplates";
import type { Write } from "../../../api/hooks/useWrite";
import type { SelectOption } from "../../../ui/primitives";

/* The api's own bounds, so the steppers offer nothing the boundary would refuse. Duplicated nowhere else:
 * these are the control's range rather than a validation rule, and the request is refused on its own terms. */
const DURATION_MINIMUM = 15;
const DURATION_MAXIMUM = 1440;
const FLEX_MAXIMUM = 720;

export interface EntryEditorProps {
  readonly areas: readonly Area[];
  readonly routines: readonly Routine[];
  readonly habits: readonly Habit[];
  readonly write: Write<EntryBody>;
}

export function EntryEditor({ areas, routines, habits, write }: EntryEditorProps) {
  const [draft, setDraft] = useState<EntryDraft>(EMPTY_ENTRY_DRAFT);
  const proposal = entryProposalFrom(draft);
  const isIncomplete = proposal.status === "incomplete";

  const bindingOptions: readonly SelectOption[] = [
    ...routines.map((routine) => ({
      value: bindingValue({ target: "routine", ref: routine.id }),
      label: `${routine.title} \u00B7 routine`,
    })),
    ...habits.map((habit) => ({
      value: bindingValue({ target: "habit", ref: habit.id }),
      label: `${habit.title} \u00B7 habit`,
    })),
  ];

  const declare = () => {
    if (proposal.status !== "declarable") return;
    void write.submit(proposal.body);
  };

  return (
    <div className="flex flex-col gap-3.25">
      {write.problem === null ? null : (
        <NoticeCard
          notice={rejectionNotice({
            id: "entry-declaration",
            problem: write.problem,
            stillWorks: "every entry this shape already holds, unchanged",
          })}
        />
      )}

      {/* The question is rendered as well as announced. The kit's radio group takes its name as a string, so
       * a sighted reader gets no heading unless the words are also drawn; a screen reader hears them twice,
       * which is the cost of a group that cannot be pointed at an existing label. Deferral 1240. */}
      <p className="text-label tracking-label uppercase text-text-muted">Kind</p>
      <Radio
        label="Kind"
        value={draft.kind}
        onValueChange={(kind) =>
          setDraft((previous) => ({
            ...previous,
            kind: kind === "slot" ? "slot" : "concrete",
          }))
        }
        options={[
          { value: "concrete", label: "concrete \u00B7 a routine or a habit, by name" },
          { value: "slot", label: "slot \u00B7 an Area and a duration, bound at plan time" },
        ]}
      />

      {draft.kind === "concrete" ? (
        <FormRow
          label="Entry"
          isRequired
          hint={isIncomplete && proposal.member === "binding" ? proposal.reason : undefined}
          error={messageFor(write.problem, "bindingRef")}
        >
          {(field) => (
            <Select
              id={field.id}
              describedBy={field.describedBy}
              value={draft.binding === null ? "" : bindingValue(draft.binding)}
              onValueChange={(value) =>
                setDraft((previous) => ({ ...previous, binding: bindingFrom(value) }))
              }
              options={bindingOptions}
              placeholder="choose a routine or a habit"
            />
          )}
        </FormRow>
      ) : (
        <FormRow
          label="Area"
          isRequired
          hint={isIncomplete && proposal.member === "area" ? proposal.reason : undefined}
          error={messageFor(write.problem, "areaId")}
        >
          {(field) => (
            <Select
              id={field.id}
              describedBy={field.describedBy}
              value={draft.areaId ?? ""}
              onValueChange={(areaId) => setDraft((previous) => ({ ...previous, areaId }))}
              options={areas.map((area) => ({ value: area.id, label: area.name }))}
              placeholder="choose an Area"
            />
          )}
        </FormRow>
      )}

      <FormRow
        label="Target"
        hint="wall time, on the quarter hour"
        error={messageFor(write.problem, "targetTime")}
      >
        {(field) => (
          <TimeInput
            id={field.id}
            describedBy={field.describedBy}
            value={draft.targetTime}
            onValueChange={(targetTime) => setDraft((previous) => ({ ...previous, targetTime }))}
          />
        )}
      </FormRow>

      <MinutesRow
        label="Duration"
        error={messageFor(write.problem, "durationMinutes")}
        min={DURATION_MINIMUM}
        max={DURATION_MAXIMUM}
        unit="minutes"
        value={draft.durationMinutes}
        onValueChange={(durationMinutes) =>
          setDraft((previous) => ({ ...previous, durationMinutes }))
        }
      />

      <MinutesRow
        label="Flex band"
        hint="how far a placement may shift the entry either way. Below one step it may not"
        error={messageFor(write.problem, "flexBandMinutes")}
        min={0}
        max={FLEX_MAXIMUM}
        unit="minutes either way"
        value={draft.flexBandMinutes}
        onValueChange={(flexBandMinutes) =>
          setDraft((previous) => ({ ...previous, flexBandMinutes }))
        }
      />

      <Button onClick={declare} isDisabled={isIncomplete}>
        Declare entry
      </Button>
    </div>
  );
}
