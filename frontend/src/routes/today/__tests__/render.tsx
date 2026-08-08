/* Rendering the Today screen at the date the host is on.
 *
 * THE DATE IS THE HOST'S, so a test cannot hard-code the path the screen will read. The handler matches the
 * date as a path parameter and answers with the day it was given, which is also how a test asserts WHICH
 * date was asked for.
 *
 * THE DAY'S SPAN IS THE HOST'S OWN MIDNIGHTS while its zone is stated as London, and the two are separate on
 * purpose: the span is what decides whether the screen says the day has ended, so it has to contain the real
 * `now` on any machine, and the zone is what every time on screen is READ in, so it has to be fixed or every
 * assertion about a clock time would depend on where the suite runs. */

import { http, HttpResponse } from "msw";

import { apiServer } from "../../../testing/apiServer";
import { readyz } from "../../../testing/apiStub";
import { renderSignedInAt } from "../../../testing/renderRoute";
import type { Areas } from "../../../api/hooks/useAreas";
import type { Day } from "../../../api/hooks/useDay";
import { hostDateOf } from "../instants";
import { buildAreas } from "./fixtures";

const origin = window.location.origin;

/** The date the screen will address, which is the host's own local date. */
export function hostToday(): string {
  return hostDateOf(new Date());
}

/** The day the host is living, so the screen does not report that the day on screen has ended. */
export function hostSpan(): { readonly start: string; readonly end: string } {
  const now = new Date();
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return { start: midnight.toISOString(), end: next.toISOString() };
}

/** The day as this screen will read it: the fixture's rows, on the date and span the host is on. */
export function onHostToday(day: Day): Day {
  return { ...day, date: hostToday(), span: hostSpan() };
}

export interface DayStub {
  /** Every date the screen asked for, in order. */
  readonly dates: string[];
  /** How many times the day was read, which is how an invalidation is observed. */
  readonly reads: () => number;
}

/** The two reads this screen makes, answered with what the test gave them. */
export function stubDay(day: Day, areas: Areas = buildAreas()): DayStub {
  const dates: string[] = [];
  let reads = 0;

  apiServer.use(
    readyz(),
    http.get(`${origin}/api/v1/areas`, () => HttpResponse.json(areas)),
    /* The sources, which the screen reads to say whether a feed the day's commitments came from can still be
     * read. Answered here with none, because the uninteresting case is a reader with no feed at all: a test
     * about a stale feed passes its own handler ahead of this one. */
    http.get(`${origin}/api/v1/calendar-sources`, () => HttpResponse.json({ sources: [] })),
    http.get(`${origin}/api/v1/days/:date`, ({ params }) => {
      dates.push(String(params.date));
      reads += 1;
      return HttpResponse.json(day);
    }),
  );

  return { dates, reads: () => reads };
}

/** The screen, rendered through the real route table at `/today`. */
export async function renderToday(day: Day, areas: Areas = buildAreas()): Promise<DayStub> {
  const stub = stubDay(day, areas);
  await renderSignedInAt("/today");
  return stub;
}

/**
 * A response the test holds until it releases it.
 *
 * The optimistic frame is a state the screen holds for one round trip, so asserting it needs a response
 * whose timing the test owns. Released before the test ends, so the invalidation that follows a write is
 * asserted rather than left running past the assertion.
 */
export function heldResponse(): { readonly held: Promise<void>; readonly release: () => void } {
  let resolveHeld: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    resolveHeld = resolve;
  });
  return { held, release: () => resolveHeld?.() };
}
