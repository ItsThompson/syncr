/* SWR cache keys.
 *
 * APPEND ONLY. One builder per resource, added at the END of this file. A mutation then
 * invalidates by naming a builder rather than by a blanket revalidation: a blanket
 * revalidation refetches the whole week when a setting changed, which is both slow and a
 * source of flicker on a surface with no animation to hide it.
 *
 * Keys are the request path, so a key read in a devtools cache entry names the resource it
 * came from without a lookup table. */

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
