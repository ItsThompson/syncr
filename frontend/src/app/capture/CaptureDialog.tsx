/* THE CAPTURE FORM. A title and an Area, and nothing else that has to be answered.
 *
 * PRESENTATIONAL: every value, every refusal and the submit arrive as props, so the form is testable without a
 * network fixture and the host above it owns the reads and the write.
 *
 * THERE IS NO PREFERRED-TIME FIELD, AND THE FORM SAYS WHY. A preferred time is a `Preference` whose owner is an
 * Area, a Habit or a Task, and the api's capture request refuses the field outright, so a control here would be a
 * second home for a value that has one. Where the reader named no stretch of time, the hint states the
 * inheritance: the task takes its Area's windows, and the place to author those is the Preference column on the
 * Areas screen.
 *
 * A WINDOW THE OPENING CARRIES IS STATED AND NOT OFFERED, AND STATING IT IS A CLAIM ABOUT THE WRITE. A reader who
 * activated a slot on the week screen came from one stretch of time, the confirm declares that stretch as this
 * task's own soft preference, and the sentence says so: a prefill a reader cannot see cannot be told from one that
 * was dropped on the way, and a write nobody was told about is worse. It is a sentence rather than a control
 * because there is nowhere for an edited one to go -- the request shape refuses the field, and the value has one
 * home, which is the preference the confirm writes.
 *
 * THE INHERITANCE SENTENCE BELONGS TO THE OPENING THAT HAS NO WINDOW, and only to it. A task whose own preference
 * this confirm declares does not inherit its Area's: saying both would state the two rules that cannot hold at
 * once. So the form states exactly one of them, chosen by whether the opening carries a window.
 *
 * THE MINIMUM CHUNK'S REFUSAL IS RENDERED AT ITS OWN ROW, with the reason, and the submit stays disabled while
 * it stands: a reader is told at the field rather than after a round trip. The rule itself is the domain's, and
 * a refusal the api returns lands on the same rows through the same prop, so the sentence a reader sees when the
 * two ever disagree is the boundary's own.
 *
 * A REQUIRED FIELD NOBODY HAS FILLED IN YET IS INCOMPLETE RATHER THAN WRONG. Its refusal is not drawn and the
 * field is not marked invalid: the required mark on the label and the disabled control are what say a title and
 * an Area are still needed, and a form that opened already complaining would be making a claim about the reader
 * rather than about a value. A value that is present and refused is stated at its own row.
 *
 * THE CARET LANDS IN THE TITLE, because `n` is a promise about speed: a reader who presses it and starts typing
 * has to be typing the title. That is the `Dialog` family's own policy rather than something arranged here: the
 * caret goes to the first control in the body, and the title is the first row. */

import { NoticeCard, type Notice } from "../../ui/domain";
import { FormRow } from "../../ui/layout";
import {
  Button,
  Checkbox,
  DatePicker,
  Dialog,
  Input,
  NumberStepper,
  Select,
} from "../../ui/primitives";
import {
  PRIORITIES,
  priorityOf,
  type CaptureDraft,
  type DraftRefusals,
  type Priority,
} from "./draft";

export interface CaptureArea {
  readonly id: string;
  readonly name: string;
}

export interface CaptureDialogProps {
  readonly isOpen: boolean;
  readonly onOpenChange: (next: boolean) => void;
  readonly draft: CaptureDraft;
  readonly onDraftChange: (next: CaptureDraft) => void;
  /** The Areas a task's time can count toward, in the order the Areas screen lists them. */
  readonly areas: readonly CaptureArea[];
  /** Why the draft cannot be sent, per member: the form's own refusals merged with the api's field errors. */
  readonly refusals: DraftRefusals;
  readonly canSubmit: boolean;
  readonly onSubmit: () => void;
  /** `YYYY-MM-DD` in the reader's own zone, which is what the date field opens on. */
  readonly today: string;
  /**
   * The window this opening's work should prefer, as the reader's own zone reads it.
   *
   * Words rather than the two instants behind them, because the zone is the host's read: the form is handed a
   * reading for the same reason it is handed today's date. Absent where the opening names no window, and absent
   * where its instants could not be read in the reader's zone, which is the same case the confirm declares no
   * preference for.
   */
  readonly preferredWindowReading?: string | undefined;
  /** Where focus returns when the dialog closes: the element the reader was on when it opened. */
  readonly returnFocusTo?: HTMLElement | null | undefined;
  /**
   * What the form has to say, at inline volume inside the dialog.
   *
   * One slot rather than one per kind, because the host is what knows which of them holds: a refusal this
   * opening was answered with, or the statement that a send it does not own is still open. A dialog rendering
   * two would be stacking notices inside a notice's own position.
   */
  readonly notice?: Notice | undefined;
}

const PRIORITY_LABELS: Record<Priority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

export function CaptureDialog({
  isOpen,
  onOpenChange,
  draft,
  onDraftChange,
  areas,
  refusals,
  canSubmit,
  onSubmit,
  today,
  preferredWindowReading,
  returnFocusTo,
  notice,
}: CaptureDialogProps) {
  const change = <Field extends keyof CaptureDraft>(field: Field, value: CaptureDraft[Field]) => {
    onDraftChange({ ...draft, [field]: value });
  };

  /* A refusal about a value the reader has not supplied yet is not drawn: an empty required field is incomplete
     rather than wrong, and it still disables the submit. */
  const stated = (field: "title" | "areaId", value: string): string | undefined =>
    value === "" ? undefined : refusals[field];

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      returnFocusTo={returnFocusTo}
      title="Capture a task"
      description="A title and an Area are all this needs. Everything else already has a default."
      footer={
        <Button isDisabled={!canSubmit} onClick={onSubmit} rank="primary">
          Capture
        </Button>
      }
    >
      {notice === undefined ? null : <NoticeCard notice={notice} />}
      <FormRow error={stated("title", draft.title)} isRequired label="Task">
        {(field) => (
          <Input
            describedBy={field.describedBy}
            id={field.id}
            isInvalid={stated("title", draft.title) !== undefined}
            isRequired
            onValueChange={(next) => change("title", next)}
            placeholder="What the work is"
            value={draft.title}
          />
        )}
      </FormRow>
      <FormRow error={stated("areaId", draft.areaId)} isRequired label="Area">
        {(field) => (
          <Select
            describedBy={field.describedBy}
            id={field.id}
            isInvalid={stated("areaId", draft.areaId) !== undefined}
            isRequired
            onValueChange={(next) => change("areaId", next)}
            options={areas.map((area) => ({ value: area.id, label: area.name }))}
            placeholder="Which Area this counts toward"
            value={draft.areaId}
          />
        )}
      </FormRow>
      <FormRow error={refusals.estimateMinutes} hint="minutes of work" label="Estimate">
        {(field) => (
          <NumberStepper
            describedBy={field.describedBy}
            id={field.id}
            isInvalid={refusals.estimateMinutes !== undefined}
            measure="duration"
            min={1}
            onValueChange={(next) => change("estimateMinutes", next)}
            unit="min"
            value={draft.estimateMinutes}
          />
        )}
      </FormRow>
      <FormRow error={refusals.deadline} hint="optional: by the end of this day" label="Deadline">
        {(field) => (
          <DatePicker
            describedBy={field.describedBy}
            id={field.id}
            isInvalid={refusals.deadline !== undefined}
            label="Deadline"
            onValueChange={(next) => change("deadline", next)}
            today={today}
            value={draft.deadline}
          />
        )}
      </FormRow>
      <FormRow error={refusals.priority} label="Priority">
        {(field) => (
          <Select
            describedBy={field.describedBy}
            id={field.id}
            onValueChange={(next) => change("priority", priorityOf(next, draft.priority))}
            options={PRIORITIES.map((priority) => ({
              value: priority,
              label: PRIORITY_LABELS[priority],
            }))}
            value={draft.priority}
          />
        )}
      </FormRow>
      <FormRow
        error={refusals.minChunkMinutes}
        hint="the smallest placement a split may leave"
        label="Minimum chunk"
      >
        {(field) => (
          <NumberStepper
            describedBy={field.describedBy}
            id={field.id}
            isInvalid={refusals.minChunkMinutes !== undefined}
            measure="duration"
            min={1}
            onValueChange={(next) => change("minChunkMinutes", next)}
            unit="min"
            value={draft.minChunkMinutes}
          />
        )}
      </FormRow>
      <FormRow error={refusals.splittable} label="Splittable">
        {(field) => (
          <Checkbox
            id={field.id}
            onStateChange={(next) => change("splittable", next === "checked")}
            state={draft.splittable ? "checked" : "unchecked"}
          >
            The solver may divide this across several placements
          </Checkbox>
        )}
      </FormRow>
      {preferredWindowReading === undefined ? (
        <p className="text-eyebrow text-text-muted">
          There is no preferred time here: a preferred time is inherited from the Area, and is
          edited in the Preference column on the Areas screen.
        </p>
      ) : (
        <p className="text-eyebrow text-text-muted">
          The slot you activated runs {preferredWindowReading}, and capturing this prefers that
          stretch for this task alone: a soft preference of its own, in place of its Area's.
        </p>
      )}
    </Dialog>
  );
}
