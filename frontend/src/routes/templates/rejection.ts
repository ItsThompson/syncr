/* A refused write, as the notice the reader sees beside the control they were editing.
 *
 * AMBER, VOLUME ONE, AND THAT PAIR IS THE WHOLE DECISION. Amber says something needs attention and nothing is
 * broken, which is exactly a refused edit: the api applied nothing and every other row still reads as it did.
 * Volume one is inline, at the thing it concerns, because the repair is the form the reader already has open.
 * Oxide would say the product is broken and a panel would put the sentence at the head of the screen, away
 * from the member to change.
 *
 * THE MEMBER IS NAMED TWICE, ON PURPOSE, and neither is a copy of a rule. The card's sentence carries the
 * api's own field-level message, so the reader learns which member to change without hunting; and
 * `messageFor` hands the same message to the row that owns that member, so the words sit at the control. Both
 * come from the response, so nothing here restates a boundary rule that could drift from it. */

import type { Problem } from "../../contract";
import type { Notice } from "../../ui/domain";

export interface RejectionInput {
  /** Distinguishes this notice from the others on the screen, and labels the card. */
  readonly id: string;
  readonly problem: Problem;
  /** What is still true, in the reader's words. A notice that says only what failed is not a notice. */
  readonly stillWorks: string;
}

/** The refusal's own sentence: the members it names first, then what the api said about the whole change. */
function detailOf(problem: Problem): string {
  const members = (problem.errors ?? []).map((error) => `${error.field} ${error.message}.`);
  return [...members, problem.detail].join(" ");
}

export function rejectionNotice({ id, problem, stillWorks }: RejectionInput): Notice {
  return {
    id,
    volume: "inline",
    pigment: "amber",
    title: problem.title,
    detail: detailOf(problem),
    unavailable: [],
    stillWorks: [stillWorks],
    since: null,
    action: null,
    scope: null,
  };
}

/** The message the refusal gave for one member, or undefined when it named another. */
export function messageFor(problem: Problem | null, field: string): string | undefined {
  if (problem === null) return undefined;
  return problem.errors?.find((error) => error.field === field)?.message;
}
