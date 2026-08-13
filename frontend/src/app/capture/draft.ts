/* THE CAPTURE DRAFT: what the form holds, what it sends, and the one pair it will not send.
 *
 * A TITLE AND AN AREA ARE THE WHOLE REQUIREMENT. Every other member of the request has a documented default on
 * the api, and this draft carries the same values so the form opens on them: `n` from any screen therefore
 * submits with two values, which is what makes capture cheap enough not to compete with the thing being
 * captured.
 *
 * THERE IS NO PREFERRED-TIME MEMBER, AND THERE CANNOT BE ONE. A preferred time is a `Preference`, whose owner
 * is an Area, a Habit or a Task, so a task inherits its Area's windows unless it overrides them. The api's
 * request shape forbids an unknown field, so a `preferredTimes` member here would be a 422 rather than a value
 * quietly dropped. A window a caller opened capture from is held by the OPENING for that reason, and never by
 * this draft: what writes it is a second request, against the task this one creates.
 *
 * THE MINIMUM-CHUNK GUARD IS AN AFFORDANCE AND NOT THE RULE. `syncr_domain.tasks` owns the comparison of a
 * minimum chunk against an estimate, it is the only statement of it in the product, and its 422 names the
 * fields it refuses. What this guard does is stop a submit that the domain would refuse, so a reader is told at
 * the field instead of after a round trip. When the two ever disagree, the boundary's own sentence is what the
 * form renders, because every field error a refusal names lands on the row it names. */

import { zonedInstant } from "../../lib/zonedInstant";
import type { TaskCaptureBody } from "../../api/hooks/useBacklog";
import type { components } from "../../api/schema";
import type { CaptureOpening } from "./captureContext";

export type Priority = components["schemas"]["Priority"];

/** The priorities, least preferred first, which is the objective's own order rather than the alphabet's. */
export const PRIORITIES: readonly Priority[] = ["low", "normal", "high", "urgent"];

/**
 * A priority chosen from a control, or the one already held where the value is not one.
 *
 * A control offering exactly these four cannot answer with anything else, so the fallback is not a case a
 * screen produces: it is what a cast would otherwise be, and a cast is an assertion the compiler cannot check.
 */
export function priorityOf(value: string, held: Priority): Priority {
  return PRIORITIES.find((priority) => priority === value) ?? held;
}

/**
 * What the form holds while it is being filled in.
 *
 * The estimate and the minimum chunk are numbers rather than the api's optional members, because a stepper
 * always has a figure in it. The deadline is the date field's own empty string when there is none, which is
 * what turns into the request's null.
 */
export interface CaptureDraft {
  readonly title: string;
  readonly areaId: string;
  readonly estimateMinutes: number;
  readonly minChunkMinutes: number;
  readonly deadline: string;
  readonly priority: Priority;
  readonly splittable: boolean;
}

/* The api's own documented defaults, restated here because a form has to open on something and the two-value
 * capture is what makes them visible. 30 minutes is two grid steps, which is the smallest estimate the default
 * minimum chunk can divide, and 15 is one step. */
const DEFAULT_ESTIMATE_MINUTES = 30;
const DEFAULT_MIN_CHUNK_MINUTES = 15;

/**
 * The draft an opening starts on: the api's own documented defaults, and whatever the caller already knows.
 *
 * No opening at all is the empty form, which is what a closed dialog holds and what `n` gets.
 *
 * THE MINIMUM CHUNK FOLLOWS AN ESTIMATE THAT SITS BELOW IT. The default floor is one grid step, so a caller
 * naming a shorter estimate would otherwise open the form on a pair it refuses, stated on a row nobody has
 * touched and with the submit disabled: a prefill that arrives already refused is worse than no prefill.
 *
 * IT TAKES THE WHOLE OPENING AND READS TWO MEMBERS OF IT, so a member added to an opening cannot silently become
 * a member of the request: what the draft holds is what the api takes.
 */
export function draftFrom(opening: CaptureOpening = {}): CaptureDraft {
  const estimateMinutes = opening.estimateMinutes ?? DEFAULT_ESTIMATE_MINUTES;
  return {
    title: "",
    areaId: opening.areaId ?? "",
    estimateMinutes,
    minChunkMinutes: Math.min(DEFAULT_MIN_CHUNK_MINUTES, estimateMinutes),
    deadline: "",
    priority: "normal",
    splittable: true,
  };
}

/** Why this draft cannot be submitted, per member, or an empty record when it can. */
export type DraftRefusals = Partial<Record<keyof CaptureDraft, string>>;

/**
 * What the form refuses before the api sees it.
 *
 * Three refusals, and each is the absence of something the api cannot supply a default for or a pair no
 * placement could satisfy. A whitespace-only title is refused here rather than trimmed silently, because a
 * reader who typed spaces meant to type words.
 */
export function refusalsIn(draft: CaptureDraft): DraftRefusals {
  const refusals: DraftRefusals = {};
  if (draft.title.trim() === "") refusals.title = "A task needs a title.";
  if (draft.areaId === "")
    refusals.areaId = "A task needs an Area, because its time counts toward one.";
  if (draft.minChunkMinutes > draft.estimateMinutes) {
    refusals.minChunkMinutes =
      "A minimum chunk larger than the estimate is refused, because no placement could satisfy both.";
  }
  return refusals;
}

/** True when nothing refuses this draft. */
export function isSubmittable(draft: CaptureDraft): boolean {
  return Object.keys(refusalsIn(draft)).length === 0;
}

/* The last minute of a local day. The api's deadline is an INSTANT and a date is not one, so a date-only
 * deadline has to be given a time, and "by the end of that day" is what a reader choosing a date means. The
 * exact boundary would be the next day's midnight, which is a day the reader did not choose and is the day the
 * table would then render back. */
const END_OF_DAY_MINUTES = 23 * 60 + 59;

/**
 * The instant a chosen deadline date names, read in the reader's own home zone.
 *
 * Null for no date chosen. A date and a zone that resolve to no instant are also null: this screen cannot
 * produce that pair, because the date field emits only `YYYY-MM-DD` and the zone comes from the settings read,
 * and the fall-through is here rather than a throw so a zone the runtime does not know cannot become a deadline
 * a day out.
 */
export function deadlineInstantOf(date: string, zone: string): string | null {
  if (date === "") return null;
  return zonedInstant({ date, minutes: END_OF_DAY_MINUTES, zone })?.instant ?? null;
}

/**
 * The request body, built from a draft the form has already found submittable.
 *
 * The title is trimmed, because trailing space in a title is not a word. The deadline arrives resolved rather
 * than resolved here, because turning a date into an instant needs the reader's zone and a draft does not
 * carry one: the screen that read the settings is what has it.
 */
export function bodyOf(draft: CaptureDraft, deadline: string | null): TaskCaptureBody {
  return {
    areaId: draft.areaId,
    title: draft.title.trim(),
    estimateMinutes: draft.estimateMinutes,
    minChunkMinutes: draft.minChunkMinutes,
    deadline,
    priority: draft.priority,
    splittable: draft.splittable,
  };
}
