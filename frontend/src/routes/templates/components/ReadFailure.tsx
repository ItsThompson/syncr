/* A read that did not arrive, as the failure surface with the api's own sentence.
 *
 * The problem's `detail` is the whole body deliberately. Every problem this api produces says what was not
 * applied and what is still true, and a screen that summarised it in its own words would be paraphrasing the
 * one sentence written to be read here. What this component adds is the title, which names the reading that
 * failed, because "Unexpected response" alone does not say which of a screen's six reads it was. */

import { ErrorState } from "../../../ui/domain";
import type { Problem } from "../../../contract";

export interface ReadFailureProps {
  /** What could not be read, in the reader's words: `The day shapes could not be read`. */
  readonly title: string;
  readonly problem: Problem;
}

export function ReadFailure({ title, problem }: ReadFailureProps) {
  return <ErrorState title={title} detail={problem.detail} />;
}
