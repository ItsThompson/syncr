/* The api's readiness, as a static reading.
 *
 * A labeled row rather than a paragraph, because the shape is fixed: a row implies a schema and
 * a paragraph implies unbounded prose.
 *
 * Three states and none of them spins: pending is a word, a failure is the problem's own
 * sentence, and the answer is one of two words. There is no spinner in the kit to paper over an
 * ambiguous state, which is why the hook returns a discriminated union rather than independent
 * booleans.
 *
 * THE LIST CARRIES A NAME because the screen it sits on states several readings. A `dd` has no
 * accessible name of its own, so naming the list is what lets a reader, and a test, say WHICH
 * definition they mean. */

import type { Readiness } from "../api/hooks/useReadiness";
import type { Resource } from "../contract";

export interface ApiReadingProps {
  readonly readiness: Resource<Readiness>;
}

function read(readiness: Resource<Readiness>): string {
  if (readiness.status === "loading") return "reading";
  if (readiness.status === "error") return readiness.problem.detail;
  return readiness.data.isReady ? "ready" : "not ready";
}

/** Names the list, so a screen stating several readings does not leave this one unidentifiable. */
export const API_READING_LABEL = "api readiness";

export function ApiReading({ readiness }: ApiReadingProps) {
  return (
    <dl
      aria-label={API_READING_LABEL}
      className="flex items-baseline gap-3.25 border-b border-rule py-2"
    >
      <dt className="w-sidebar shrink-0 text-eyebrow tracking-eyebrow uppercase text-text-muted">
        api
      </dt>
      <dd className="text-sm text-ink">{read(readiness)}</dd>
    </dl>
  );
}
