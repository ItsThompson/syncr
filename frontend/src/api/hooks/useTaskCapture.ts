/* CAPTURING A TASK, AND THE PREFERENCE THE SAME CONFIRM WRITES FOR IT.
 *
 * TWO REQUESTS BEHIND ONE CONFIRM, AND THE SECOND NEEDS THE FIRST'S ANSWER. A preference is addressed by its
 * owner, so the task has to exist before a window can be declared on it, and the capture's own response carries
 * the identifier the second request goes to. That ordering is why these are one hook rather than two a form
 * calls in turn: a caller sequencing them would be holding the identifier and the failure model as well.
 *
 * A PREFERRED WINDOW IS A COST AND A PIN IS A CONSTRAINT, so this writes the first and never the second. A
 * reader who activated an empty slot said where the work belongs; they did not say it may go nowhere else, and
 * a pin on a block of the plan of record is that second sentence. No request here goes to a week.
 *
 * WHICH OF THE TWO DID NOT LAND IS THE ANSWER, because the two refusals leave two different worlds: a refused
 * capture leaves nothing behind, and a refused preference leaves a task the reader can see in their list beside
 * a window nobody recorded. A boolean cannot tell those apart, so `submit` answers the outcome and the surface
 * above it decides what to say.
 *
 * THE LIST IS RE-READ WHATEVER THE PREFERENCE DID, once, after both. The task is in it either way, and a
 * captured task the reader cannot see would be a worse answer to a refused preference than a task whose
 * preferred window is missing.
 *
 * THE TASK-ADDRESSED PREFERENCE IS WRITTEN HERE AND NOT IN `usePreferences`, which owns the Area-addressed set
 * the Areas table draws. This is the only writer of a task's own preference in the product. The day a surface
 * edits one, its write belongs beside the Area's rather than here.
 *
 * NOTHING IS OPTIMISTIC. A capture's answer carries the server's own defaults, the identifier the second request
 * is addressed to, and the task's place in the ordering, none of which is predictable here. */

import { useState } from "react";
import { useSWRConfig } from "swr";

import { client } from "../client";
import { isBacklogKey } from "../keys";
import { apply, answered } from "./request";
import { idempotentHeaders } from "./useWrite";
import type { TaskCaptureBody } from "./useBacklog";
import type { PreferenceStrength } from "./usePreferences";
import type { Problem } from "../../contract";
import type { components } from "../schema";

/** One preferred stretch of the day as the caller states it: two wall times, no date and no zone. */
export type PreferredWindow = components["schemas"]["TimeWindowRequest"];

type TaskPreferenceBody = components["schemas"]["OverridePreferenceRequest"];

/** One confirm of the capture form: the task to create, and the window it should prefer where there is one. */
export interface TaskCapture {
  readonly task: TaskCaptureBody;
  readonly preferredWindow: PreferredWindow | null;
}

/** Which of a capture's two writes a refusal belongs to. */
export type CaptureWrite = "task" | "preference";

/**
 * What one confirm did: nothing refused, or which of the two writes was refused and why.
 *
 * One shape rather than a boolean beside a problem, so a refusal without a write to blame it on and a write
 * blamed with no refusal are both unspellable.
 */
export type CaptureOutcome =
  | { readonly refused: null; readonly problem: null }
  | { readonly refused: CaptureWrite; readonly problem: Problem };

const LANDED: CaptureOutcome = { refused: null, problem: null };

/* SOFT RATHER THAN STRONG. Activating a slot names a stretch of time the work belongs in. It does not say that
 * placing the work elsewhere costs an order of magnitude more, which is what strong says, and a reader who
 * means that can only mean it deliberately: the choice belongs to a surface that offers it. */
const CAPTURED_STRENGTH: PreferenceStrength = "soft";

export interface TaskCaptureWrite {
  /** Sends the capture, then the preference a window asks for, and answers which of them did not land. */
  readonly submit: (capture: TaskCapture) => Promise<CaptureOutcome>;
  /** The last refusal, whichever of the two it belongs to, or null since the last confirm that landed whole. */
  readonly problem: Problem | null;
}

/**
 * Capturing a task, which is the one write reachable from every screen.
 *
 * The task's body is the request shape itself rather than a flattened set of parameters, so the two required
 * members and every documented default are the api's own contract at the call site.
 */
export function useTaskCapture(): TaskCaptureWrite {
  const { mutate } = useSWRConfig();
  const [problem, setProblem] = useState<Problem | null>(null);

  const submit = async (capture: TaskCapture): Promise<CaptureOutcome> => {
    const outcome = await sent(capture, () => mutate(isBacklogKey));
    setProblem(outcome.problem);
    return outcome;
  };

  return { submit, problem };
}

/** The two requests, in the order the second one's address requires, and the one re-read that follows them. */
async function sent(
  { task, preferredWindow }: TaskCapture,
  invalidate: () => Promise<unknown>,
): Promise<CaptureOutcome> {
  const captured = await answered(() =>
    client.POST("/api/v1/tasks", { headers: idempotentHeaders(), body: task }),
  );
  if (captured.problem !== null) return { refused: "task", problem: captured.problem };

  const refusal =
    preferredWindow === null ? null : await declared(captured.body.id, preferredWindow);
  await invalidate();
  return refusal === null ? LANDED : { refused: "preference", problem: refusal };
}

/** The task's own preference: the window it was captured from, replacing its Area's wholly. */
async function declared(taskId: string, window: PreferredWindow): Promise<Problem | null> {
  /* An ideal session length is stated as null rather than left out. The shape replaces wholly, so the two
   * spellings mean the same thing, and a slot the reader activated says when the work belongs and nothing
   * about how long one sitting of it should run. */
  const body: TaskPreferenceBody = {
    windows: [window],
    strength: CAPTURED_STRENGTH,
    preferredDurationMinutes: null,
  };
  return apply(() =>
    client.PUT("/api/v1/tasks/{task_id}/preference", {
      params: { path: { task_id: taskId } },
      headers: idempotentHeaders(),
      body,
    }),
  );
}
