/* A refused write, as the api's own sentence.
 *
 * WHY THIS IS NOT A `NoticeCard`. A notice's type requires it to name a surviving capability, and an api refusal
 * already does that in its `detail`: every problem this api produces says what was not applied and what is still
 * true. Wrapping one in a notice would mean inventing a `stillWorks` list beside a sentence that already carries
 * one, which is the same fact twice with a chance to disagree.
 *
 * WHY NOT `FormRow`'s ERROR EITHER. A row's error belongs to a field, and it is used for exactly that wherever a
 * refusal names a member. What this component is for is the refusal with no field to sit under: a 409 on an
 * overlapping period, a second write target, a removal the api will not make.
 *
 * OXIDE'S TEXT STEP, NOT ITS MARKER STEP. `--signal-oxide` carries dots, rules and glyphs at 3:1; words have to
 * clear 4.5:1 and take `--oxide-ink`. `FormRow` makes the same distinction for the same reason, and its test
 * asserts the message does not reach for the marker step.
 *
 * `role="alert"` because a refusal is something that just happened to a reader who pressed a control, and it is
 * the one thing on this screen that has to interrupt what a screen reader was saying. */

import type { Problem } from "../../../contract";

export interface RefusalProps {
  /** The first refusal to state, or null when nothing has been refused. */
  readonly problem: Problem | null;
}

export function Refusal({ problem }: RefusalProps) {
  if (problem === null) return null;
  return (
    <p role="alert" className="text-sm text-oxide-ink">
      {problem.detail}
    </p>
  );
}
