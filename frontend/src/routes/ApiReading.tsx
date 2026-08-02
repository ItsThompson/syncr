/* The api's readiness, as a static reading.
 *
 * A labeled row rather than a paragraph, because the shape is fixed: a row implies a schema and
 * a paragraph implies unbounded prose.
 *
 * Three states and none of them spins: pending is a word, a failure is the problem's own
 * sentence, and the answer is one of two words. There is no spinner in the kit to paper over an
 * ambiguous state, which is why the hook returns a discriminated union rather than independent
 * booleans. */

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

export function ApiReading({ readiness }: ApiReadingProps) {
  return (
    <dl className="flex items-baseline gap-3.25 border-b border-rule py-2">
      <dt className="w-sidebar shrink-0 text-eyebrow tracking-eyebrow uppercase text-text-muted">
        api
      </dt>
      <dd className="text-sm text-ink">{read(readiness)}</dd>
    </dl>
  );
}
