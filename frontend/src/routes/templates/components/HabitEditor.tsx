/* Editing one habit: what it is called, how often, how long, and what a miss does.
 *
 * WHAT THIS FORM DOES NOT OFFER IS THE POINT OF IT. There is no cursor control and no debt control, because
 * both are projections of the confirmed outcome log: the patch shape has no member for either and an unknown
 * member is refused, so a control here would have nothing to send. A wrong cursor means a wrong confirmation,
 * and it is fixed by correcting the day on Today, which re-derives this with no further action. The two
 * readings are rendered beside the form instead, so the provenance sits where a control would have been.
 *
 * THE AREA IS NOT OFFERED EITHER. It is declared once, because moving it would re-attribute hours that have
 * already been reported.
 *
 * A COUNT ARRIVES AS TEXT and the form refuses to submit text that is not a whole number. Every BOUND belongs
 * to the api: a count of zero is sent and refused with the member named, because a second copy of that bound
 * in the browser is a second thing to keep true. */

import { useState } from "react";

import { NoticeCard } from "../../../ui/domain";
import { FormRow } from "../../../ui/layout";
import { Button, Input, Select } from "../../../ui/primitives";
import {
  habitDraftFrom,
  habitProposalFrom,
  type HabitDraft,
  type HabitMember,
} from "../habitDraft";
import { messageFor, rejectionNotice } from "../rejection";
import { MinutesRow } from "./MinutesRow";
import type { Habit, HabitEdit } from "../../../api/hooks/useHabits";
import type { Write } from "../../../api/hooks/useWrite";

const DURATION_MINIMUM = 15;
const DURATION_MAXIMUM = 1440;

const CADENCE_OPTIONS = [
  { value: "times_per_week", label: "a count per week" },
  { value: "daily", label: "daily" },
  { value: "every_approx_days", label: "roughly every N days" },
];

const MISS_OPTIONS = [
  { value: "forgive", label: "forgive \u00B7 the occurrence vanishes" },
  { value: "debt", label: "debt \u00B7 it is owed and rescheduled" },
  { value: "escalate", label: "escalate \u00B7 it is raised in the weekly session" },
];

export interface HabitEditorProps {
  readonly habit: Habit;
  readonly write: Write<HabitEdit>;
}

export function HabitEditor({ habit, write }: HabitEditorProps) {
  /* Keyed by the habit's identifier at the call site, so choosing another habit mounts a fresh draft rather
   * than showing one habit's values under another's name. */
  const [draft, setDraft] = useState<HabitDraft>(() => habitDraftFrom(habit));
  const proposal = habitProposalFrom(draft);
  const isIncomplete = proposal.status === "incomplete";
  const reasonFor = (member: HabitMember): string | undefined =>
    isIncomplete && proposal.member === member ? proposal.reason : undefined;
  /* One member, two controls. The api refuses `cadence` as a whole, so its message lands on the count when
   * there is one and on the kind otherwise: rendering it on both would put the same sentence in the form twice
   * and leave a reader looking for two mistakes. */
  const isCountShown = draft.cadenceKind !== "daily";
  const cadenceError = messageFor(write.problem, "cadence");

  return (
    <div className="flex flex-col gap-3.25">
      {write.problem === null ? null : (
        <NoticeCard
          notice={rejectionNotice({
            id: "habit-edit",
            problem: write.problem,
            stillWorks: "this habit as it was, and every occurrence already recorded",
          })}
        />
      )}

      <FormRow
        label="Title"
        isRequired
        hint={reasonFor("title")}
        error={messageFor(write.problem, "title")}
      >
        {(field) => (
          <Input
            id={field.id}
            describedBy={field.describedBy}
            value={draft.title}
            onValueChange={(title) => setDraft((previous) => ({ ...previous, title }))}
          />
        )}
      </FormRow>

      <FormRow label="Cadence" error={isCountShown ? undefined : cadenceError}>
        {(field) => (
          <Select
            id={field.id}
            describedBy={field.describedBy}
            value={draft.cadenceKind}
            onValueChange={(kind) =>
              setDraft((previous) => ({
                ...previous,
                cadenceKind:
                  kind === "daily" || kind === "every_approx_days" ? kind : "times_per_week",
              }))
            }
            options={CADENCE_OPTIONS}
          />
        )}
      </FormRow>

      {draft.cadenceKind === "daily" ? null : (
        <FormRow
          label={draft.cadenceKind === "times_per_week" ? "Times a week" : "Every N days"}
          isRequired
          hint={reasonFor("cadenceCount")}
          error={cadenceError}
        >
          {(field) => (
            <Input
              id={field.id}
              describedBy={field.describedBy}
              measure="figure"
              value={draft.cadenceCount}
              onValueChange={(cadenceCount) =>
                setDraft((previous) => ({ ...previous, cadenceCount }))
              }
            />
          )}
        </FormRow>
      )}

      <MinutesRow
        label="Least"
        hint="the floor of one occurrence"
        error={messageFor(write.problem, "minDurationMinutes")}
        min={DURATION_MINIMUM}
        max={DURATION_MAXIMUM}
        unit="minutes"
        value={draft.minDurationMinutes}
        onValueChange={(minDurationMinutes) =>
          setDraft((previous) => ({ ...previous, minDurationMinutes }))
        }
      />

      <MinutesRow
        label="Most"
        hint="equal to the floor means the duration is fixed"
        error={messageFor(write.problem, "maxDurationMinutes")}
        min={DURATION_MINIMUM}
        max={DURATION_MAXIMUM}
        unit="minutes"
        value={draft.maxDurationMinutes}
        onValueChange={(maxDurationMinutes) =>
          setDraft((previous) => ({ ...previous, maxDurationMinutes }))
        }
      />

      <FormRow label="On miss" error={messageFor(write.problem, "missPolicy")}>
        {(field) => (
          <Select
            id={field.id}
            describedBy={field.describedBy}
            value={draft.missPolicy}
            onValueChange={(policy) =>
              setDraft((previous) => ({
                ...previous,
                missPolicy: policy === "debt" || policy === "escalate" ? policy : "forgive",
              }))
            }
            options={MISS_OPTIONS}
          />
        )}
      </FormRow>

      <FormRow
        label="Debt cap"
        isRequired
        hint={reasonFor("debtCapPeriods") ?? "in cadence periods. A miss at the cap is forgiven"}
        error={messageFor(write.problem, "debtCapPeriods")}
      >
        {(field) => (
          <Input
            id={field.id}
            describedBy={field.describedBy}
            measure="figure"
            value={draft.debtCapPeriods}
            onValueChange={(debtCapPeriods) =>
              setDraft((previous) => ({ ...previous, debtCapPeriods }))
            }
          />
        )}
      </FormRow>

      <Button
        isDisabled={isIncomplete}
        onClick={() => {
          if (proposal.status === "declarable") void write.submit(proposal.body);
        }}
      >
        Save the habit
      </Button>
    </div>
  );
}
