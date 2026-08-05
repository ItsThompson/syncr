/* A section of a screen that renders from several reads, and the two states it has before they land.
 *
 * ONE PLACE FOR THE THREE-WAY BRANCH. A screen with six reads narrowed into four readings would otherwise repeat
 * `loading -> pending surface, error -> failure surface, ready -> the panels` four times, and the fourth copy is
 * where one of them comes to render a failure as an empty state.
 *
 * A REFUSAL OUTRANKS AN OUTSTANDING READ, and `readingOf` has already made that choice: the reading handed here is
 * a failure if any of its resources failed, whatever the others are still doing. This component renders it.
 *
 * NEITHER STATE SPINS. Pending is a sentence naming what is outstanding, which is more than a spinner ever said,
 * and a failure is the api's own sentence, which names what was not applied and what is still true. */

import type { ReactNode } from "react";

import { ErrorState, PendingState } from "../../../ui/domain";
import type { Reading } from "../../reading";

export interface ReadingSectionProps<Data extends Record<string, unknown>> {
  readonly reading: Reading<Data>;
  /** What is being waited for: `Reading your calendars`. */
  readonly title: string;
  /** What is known meanwhile, and what the reads are for. */
  readonly detail: string;
  readonly children: (data: Data) => ReactNode;
}

export function ReadingSection<Data extends Record<string, unknown>>({
  reading,
  title,
  detail,
  children,
}: ReadingSectionProps<Data>) {
  if (reading.status === "loading") return <PendingState title={title} detail={detail} />;
  if (reading.status === "error") {
    return (
      <ErrorState title={`The ${reading.name} could not be read`} detail={reading.problem.detail} />
    );
  }
  return <>{children(reading.data)}</>;
}
