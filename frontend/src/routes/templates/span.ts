/* The span the commitments table reads over.
 *
 * A FORTNIGHT FROM NOW, which is the horizon a calendar source projects by default. The table on the anchor
 * types tab exists to show what the rules do to real commitments, so it wants the commitments a reader is
 * about to live through rather than every one the feed holds.
 *
 * `now` IS A PARAMETER. A module that read the clock itself could not be tested, and the screen has to hold
 * the span still anyway: a span recomputed on every render is a new cache key on every render, which turns one
 * read into an unbounded series of them.
 *
 * Pure: no React, no client, no DOM. */

const DAYS = 14;
const MILLISECONDS_IN_DAY = 24 * 60 * 60 * 1000;

export interface Span {
  /** An ISO instant carrying an offset, which the api requires. */
  readonly from: string;
  readonly to: string;
}

export function fortnightFrom(now: Date): Span {
  return {
    from: now.toISOString(),
    to: new Date(now.getTime() + DAYS * MILLISECONDS_IN_DAY).toISOString(),
  };
}
