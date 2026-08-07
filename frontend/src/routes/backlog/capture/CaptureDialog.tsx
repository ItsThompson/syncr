/* THE CAPTURE FORM. A title and an Area, and nothing else that has to be answered.
 *
 * PRESENTATIONAL: every value, every refusal and the submit arrive as props, so the form is testable without a
 * network fixture and the host above it owns the reads and the write.
 *
 * THERE IS NO PREFERRED-TIME FIELD, AND THE FORM SAYS WHY. A preferred time is a `Preference` whose owner is an
 * Area, so a task inherits its Area's windows unless it overrides them, and the place to author one is the
 * Preference column on the Areas screen. A control here would be a second home for a value with one home, and
 * the api's request shape refuses the field outright, so the hint states the inheritance instead.
 *
 * THE MINIMUM CHUNK'S REFUSAL IS RENDERED AT ITS OWN ROW, with the reason, and the submit stays disabled while
 * it stands: a reader is told at the field rather than after a round trip. The rule itself is the domain's, and
 * a refusal the api returns lands on the same rows through the same prop, so the sentence a reader sees when the
 * two ever disagree is the boundary's own. */

import { NoticeCard, type Notice } from "../../../ui/domain";
import { FormRow } from "../../../ui/layout";
import {
  Button,
  Checkbox,
  DatePicker,
  Dialog,
  Input,
  NumberStepper,
  Select,
} from "../../../ui/primitives";
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
  /** Where focus returns when the dialog closes: the element the reader was on when it opened. */
  readonly returnFocusTo?: HTMLElement | null | undefined;
  /** The refusal the api answered with, at inline volume, or null when nothing has been refused. */
  readonly refusal?: Notice | undefined;
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
  returnFocusTo,
  refusal,
}: CaptureDialogProps) {
  const change = <Field extends keyof CaptureDraft>(field: Field, value: CaptureDraft[Field]) => {
    onDraftChange({ ...draft, [field]: value });
  };

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
      {refusal === undefined ? null : <NoticeCard notice={refusal} />}
      <FormRow error={refusals.title} isRequired label="Task">
        {(field) => (
          <Input
            describedBy={field.describedBy}
            id={field.id}
            isInvalid={refusals.title !== undefined}
            isRequired
            onValueChange={(next) => change("title", next)}
            placeholder="What the work is"
            value={draft.title}
          />
        )}
      </FormRow>
      <FormRow error={refusals.areaId} isRequired label="Area">
        {(field) => (
          <Select
            describedBy={field.describedBy}
            id={field.id}
            isInvalid={refusals.areaId !== undefined}
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
      <p className="text-eyebrow text-text-muted">
        There is no preferred time here: a preferred time is inherited from the Area, and is edited
        in the Preference column on the Areas screen.
      </p>
    </Dialog>
  );
}
