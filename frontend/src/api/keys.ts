/* SWR cache keys.
 *
 * APPEND ONLY. One builder per resource, added at the END of this file. A mutation then
 * invalidates by naming a builder rather than by a blanket revalidation: a blanket
 * revalidation refetches the whole week when a setting changed, which is both slow and a
 * source of flicker on a surface with no animation to hide it.
 *
 * Keys are the request path, so a key read in a devtools cache entry names the resource it
 * came from without a lookup table. */

import type { components } from "./schema";

export const readinessKey = (): string => "/readyz";
export const sessionKey = (): string => "/auth/session";

export const areasKey = (): string => "/api/v1/areas";
export const routinesKey = (): string => "/api/v1/routines";
export const dayTypesKey = (): string => "/api/v1/day-types";
export const dayShapesKey = (): string => "/api/v1/templates";
export const dayShapeKey = (templateId: string): string => `/api/v1/templates/${templateId}`;
export const weekPatternKey = (): string => "/api/v1/week-pattern";
export const habitsKey = (): string => "/api/v1/habits";
export const anchorTypesKey = (): string => "/api/v1/anchor-types";
export const calendarSourcesKey = (): string => "/api/v1/calendar-sources";

/* The span is part of the key, because two spans are two resources: a page read for this fortnight
 * must not be handed back for the next one. Built with `URLSearchParams` so the key is the request
 * the client will send rather than a second spelling of it. */
export const anchorsKey = (from: string, to: string): string =>
  `/api/v1/anchors?${new URLSearchParams({ from, to }).toString()}`;

/* The date is part of the key for the reason a span is: two dates are two ledgers. Recording an outcome
 * and confirming a day each change one day, and a backfill changes the count of unconfirmed days the day
 * on screen carries, so all three name this key. */
export const dayKey = (date: string): string => `/api/v1/days/${date}`;

export const settingsKey = (): string => "/api/v1/settings";
export const travelOverridesKey = (): string => "/api/v1/settings/travel-overrides";
export const offPlanKey = (): string => "/api/v1/off-plan";

/* The Google account's own state, which is where the write target's expiry notices come from. A
 * separate key from the sources it belongs to: a reconnect changes this and not the source list, and a
 * source's inclusion changes the list and not this. */
export const googleConnectionKey = (): string => "/api/v1/calendar-sources/google/connection";

/* The period is part of the key, because two periods are two reviews: the quarter ending at this
 * week is not the quarter ending at the last one. Built with `URLSearchParams` so the key is the
 * request the client will send rather than a second spelling of it. Applying a revision changes
 * every Area's target, so the apply names this key and the Area list's.
 */
export const budgetReviewKey = (period: string): string =>
  `/api/v1/reviews/budget?${new URLSearchParams({ period }).toString()}`;

/* One key for the whole set of Area preferences, not one per Area. The routes are addressed per
 * owner, so reading them is a request each; the SET is what a surface renders, because the Areas
 * table draws a Preference cell on every row and a table cannot draw two thirds of a column. The
 * Area ids are in the key so declaring an Area does not hand back a set that has no row for it. */
export const areaPreferencesKey = (areaIds: readonly string[]): string =>
  `/api/v1/areas/preferences?${new URLSearchParams({ areas: [...areaIds].toSorted().join(",") }).toString()}`;

/* The week is part of the key, because two weeks are two plans. Every write on the Week screen names it: a
 * pin, an approval, a requested solve and a tradeoff each change one week, and a blanket revalidation would
 * refetch a whole week's plan because a setting changed, which is slow and is a source of flicker on a
 * surface with no animation to hide it. */
export const weekKey = (isoWeek: string): string => `/api/v1/weeks/${isoWeek}`;

/* One operation, by identifier. The POLLING FALLBACK's key and nothing else: an operation is normally learned
 * from the mutation that created it and from the push stream, so this key exists for the window in which the
 * stream is not connected. It is the request path, so the key names the read it will perform. */
export const operationKey = (operationId: string): string => `/api/v1/operations/${operationId}`;

/* THE BACKLOG, AND ITS FILTERS, BECAUSE TWO FILTERS ARE TWO RESOURCES. A read narrowed to the rows the
 * week's verdict marks must not be handed back for the whole list, and the at-risk narrowing is the
 * server's determination rather than something a client can reproduce, so the filter belongs in the key
 * the same way a week does. Absent members are omitted rather than sent empty, so the unfiltered read's
 * key is the bare path and matches the request the client will send. */
const BACKLOG_PATH = "/api/v1/tasks";

export interface BacklogFilters {
  readonly areaId?: string | undefined;
  readonly status?: components["schemas"]["TaskStatus"] | undefined;
  readonly atRisk?: boolean | undefined;
}

export const backlogKey = (filters: BacklogFilters = {}): string => {
  const query = new URLSearchParams();
  if (filters.areaId !== undefined) query.set("areaId", filters.areaId);
  if (filters.status !== undefined) query.set("status", filters.status);
  if (filters.atRisk !== undefined) query.set("atRisk", String(filters.atRisk));
  const stated = query.toString();
  return stated === "" ? BACKLOG_PATH : `${BACKLOG_PATH}?${stated}`;
};

/**
 * True for a backlog key whatever filters it carries, which is what a capture has to invalidate.
 *
 * ONE RESOURCE WITH SEVERAL KEYS IS THE REASON THIS EXISTS, and it is not a blanket revalidation: a
 * capture changes the list under every filter, and a reader who narrowed the table and narrowed it back
 * would otherwise meet a cached list the new task is missing from. The `?` is load-bearing, so
 * `/api/v1/tasks/{id}` is not matched: a task read by identifier is a different resource and a capture
 * changes none of them.
 */
export const isBacklogKey = (key: unknown): boolean =>
  typeof key === "string" && (key === BACKLOG_PATH || key.startsWith(`${BACKLOG_PATH}?`));
