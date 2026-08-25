/* The api double.
 *
 * msw rather than a stubbed global, because the client captures `fetch` when it is created and a
 * later stub would never be reached: intercepting at the network layer tests the real client,
 * the real request it builds, and the real response parsing.
 *
 * Handlers are keyed by request path, not by call order, so adding or reordering a request in a
 * component cannot break an unrelated test. */

import { delay, http, HttpResponse, type RequestHandler } from "msw";

import type { Problem } from "../contract";

export interface StubbedResponse {
  readonly status: number;
  readonly body?: unknown;
}

/* The client builds absolute URLs against the document's origin, so handlers are declared
 * against the same origin rather than a wildcard: an interceptor that quietly matches nothing
 * lets a request reach a real socket and the failure reads as an unreachable api. */
const url = (path: string): string => `${window.location.origin}${path}`;

export function jsonHandler(path: string, stubbed: StubbedResponse): RequestHandler {
  return http.get(url(path), () =>
    HttpResponse.json(stubbed.body ?? null, { status: stubbed.status }),
  );
}

/** How many times a stubbed GET has been answered, which is how a revalidation is observed. */
export interface CountedHandler {
  readonly handler: RequestHandler;
  readonly count: () => number;
}

/**
 * A GET that counts its answers.
 *
 * A mutation is required to invalidate by explicit key rather than by a blanket revalidation, and the only
 * observable difference is WHICH reads run again. Counting them is what makes that assertable: the keys a write
 * names are read a second time and the keys it does not name are not.
 */
export function countedHandler(path: string, stubbed: StubbedResponse): CountedHandler {
  let answered = 0;
  const handler = http.get(url(path), () => {
    answered += 1;
    return HttpResponse.json(stubbed.body ?? null, { status: stubbed.status });
  });
  return { handler, count: () => answered };
}

/** The unsafe methods, which a read stub cannot answer for. */
export type WriteMethod = "post" | "put" | "patch" | "delete";

/** Any method these stubs answer for. */
export type HandledMethod = "get" | WriteMethod;

export interface RecordingHandler {
  readonly handler: RequestHandler;
  /** Every body the api was sent, parsed, in order. */
  readonly bodies: unknown[];
}

/**
 * An unsafe method that records what it was sent.
 *
 * The body is the whole contract of a write, so a hook test asserts the request the client actually built:
 * the path it went to, and the members it carried. Recording it here rather than in each test keeps one
 * definition of "what was sent".
 *
 * A DELETE names its subject in the path and carries no body, so it records `null`: what a test asserts about one
 * is that it was sent at all, and to which path.
 */
export function recordingHandler(
  method: WriteMethod,
  path: string,
  stubbed: StubbedResponse,
): RecordingHandler {
  const bodies: unknown[] = [];
  const handler = http[method](url(path), async ({ request }) => {
    bodies.push(await request.json().catch(() => null));
    return HttpResponse.json(stubbed.body ?? null, { status: stubbed.status });
  });
  return { handler, bodies };
}

/** A path whose request never completes, standing in for an unreachable api. */
export function unreachableHandler(path: string, method: HandledMethod = "get"): RequestHandler {
  return http[method](url(path), () => HttpResponse.error());
}

/** A path whose request never answers, so a pending reading can be asserted deterministically. */
export function pendingHandler(path: string): RequestHandler {
  return http.get(url(path), async () => {
    await delay("infinite");
    return HttpResponse.json(null);
  });
}

export const readyResponse: StubbedResponse = {
  status: 200,
  body: { status: "ready", checks: { postgres: { ok: true, detail: null } } },
};

export const notReadyChecks = {
  postgres: { ok: true, detail: null },
  migrations: { ok: false, detail: "head not applied" },
};

export const notReadyResponse: StubbedResponse = {
  status: 503,
  body: { status: "not_ready", checks: notReadyChecks },
};

export const sessionResponse: StubbedResponse = {
  status: 200,
  body: {
    tenantId: "1e3c9f4c-8a2e-4a1b-9a5f-3f6b2c9d1a77",
    userId: "7d2b1a90-4c6e-4f3a-8b21-5c9e0d4f6a12",
    email: "reader@example.com",
    expiresAt: "2026-08-30T09:00:00+00:00",
  },
};

export const signedOutResponse: StubbedResponse = {
  status: 401,
  body: {
    type: "syncr:unauthorized",
    title: "Authentication required",
    status: 401,
    detail: "Sign in to continue.",
  },
};

/* An origin this deployment does not serve. Not a signed-out state: the credential was never
 * the problem, so the gate must not send the reader to sign in. */
export const originRejectedResponse: StubbedResponse = {
  status: 403,
  body: {
    type: "syncr:origin-rejected",
    title: "Cross-origin request rejected",
    status: 403,
    detail:
      "This request states an origin this deployment does not serve, so it was not applied. " +
      "Nothing was changed. Reading is unaffected.",
  },
};

export const readyz = (stubbed: StubbedResponse = readyResponse): RequestHandler =>
  jsonHandler("/readyz", stubbed);

export const session = (stubbed: StubbedResponse = sessionResponse): RequestHandler =>
  jsonHandler("/auth/session", stubbed);

/* WHY THIS IS A DEFAULT AND NOT SOMETHING EACH TEST INSTALLS. The shell reads the Google connection on every
 * screen, because the write target's expiry is a banner and a banner outlives the screen that explains it. So every
 * render through the gate issues this request, and the uninteresting case is a tenant with no account connected and
 * nothing degraded: a test that cares says so by overriding the handler. */
export const googleConnectionResponse: StubbedResponse = {
  status: 200,
  body: { configured: true, connected: false, grantedScopes: [], notices: [] },
};

export const googleConnection = (
  stubbed: StubbedResponse = googleConnectionResponse,
): RequestHandler => jsonHandler("/api/v1/calendar-sources/google/connection", stubbed);

/* THE PUSH STREAM, WHICH EVERY RENDER THROUGH THE GATE OPENS. The shell owns one connection for the whole
 * application, so it is a default for the reason the session is: the uninteresting case is a connection that is
 * open and has nothing to say. A test that drives the lifecycle installs `eventStream()` and pushes frames. */
export const EVENTS_PATH = "/api/v1/events";

export interface EventStreamStub {
  readonly handler: RequestHandler;
  /** One frame, in the api's own format, to every reader currently connected. */
  readonly push: (type: string, data: unknown) => void;
  /** Close every connection, which is what engages a polling fallback. */
  readonly drop: () => void;
  /** How many readers have connected, which is how a reconnect is observed. */
  readonly connections: () => number;
}

/**
 * A stream a test writes to.
 *
 * THE FRAME IS THE API'S, byte for byte: `event: <type>`, one `data:` line of compact JSON, and a blank line.
 * `syncr_api.events.envelopes.as_frame` is what produces it in production, so a test driving this exercises the
 * real parser over the real wire format rather than a stub of the parser's own output.
 */
export function eventStream(): EventStreamStub {
  const open = new Set<ReadableStreamDefaultController<Uint8Array>>();
  const encoder = new TextEncoder();
  let connections = 0;

  const handler = http.get(url(EVENTS_PATH), () => {
    connections += 1;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        open.add(controller);
        /* The heartbeat the api opens with: a comment, so a client's own reader sees a live connection before any
         * event exists to send. */
        controller.enqueue(encoder.encode(": heartbeat\n\n"));
      },
    });
    return new HttpResponse(body, {
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-store" },
    });
  });

  return {
    handler,
    connections: () => connections,
    push: (type, data) => {
      const frame = `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
      for (const controller of open) controller.enqueue(encoder.encode(frame));
    },
    drop: () => {
      for (const controller of open) controller.close();
      open.clear();
    },
  };
}

/** The default: a connection that opens, stays open, and never has anything to say. */
export const events = (): RequestHandler => eventStream().handler;

/**
 * A stream the api will not open.
 *
 * The shape a degraded api or a proxy in the way produces, and the only condition the polling fallback keys on: a
 * reader that cannot open the connection reports it as closed rather than treating a status body as frames.
 */
export const refusedEventStream = (status = 503): RequestHandler =>
  http.get(url(EVENTS_PATH), () =>
    HttpResponse.json({ title: "Service unavailable", status }, { status }),
  );

/* THE TWO READS THE CAPTURE HOST MAKES, and they are defaults for the reason the connection is: the host is
 * mounted inside the gate, so every render through it asks for both. A capture needs an Area, and a deadline
 * needs the reader's home zone.
 *
 * THE UNINTERESTING CASE IS AN ACCOUNT WITH NOTHING DECLARED, which is what an empty Area list is: the form then
 * offers no Area and refuses to submit, which is a real state rather than a broken one. A test about capture says
 * what it needs by overriding these, the way a test about a banner overrides the connection. */
export const areasResponse: StubbedResponse = {
  status: 200,
  body: {
    areas: [],
    ramp: { pigmentCount: 12, pigmentsInUse: 0 },
  },
};

export const areas = (stubbed: StubbedResponse = areasResponse): RequestHandler =>
  jsonHandler("/api/v1/areas", stubbed);

export const settingsResponse: StubbedResponse = {
  status: 200,
  body: {
    homeZone: "Europe/London",
    activeZone: "Europe/London",
    activeZoneDate: "2026-02-12",
    dayStart: "06:00",
    dayEnd: "23:00",
    visibleHours: 16,
    reviewCadence: "quarterly",
  },
};

export const settings = (stubbed: StubbedResponse = settingsResponse): RequestHandler =>
  jsonHandler("/api/v1/settings", stubbed);

/* THE SOURCE LIST, WHICH THREE SCREENS READ. Settings manages them, Templates scopes an anchor rule to one, and
 * Today asks whether a feed the day's commitments came from can still be read. The uninteresting case is a reader
 * with no feed at all, which is also a first-run state rather than a broken one. */
export const calendarSourcesResponse: StubbedResponse = { status: 200, body: { sources: [] } };

export const calendarSources = (
  stubbed: StubbedResponse = calendarSourcesResponse,
): RequestHandler => jsonHandler("/api/v1/calendar-sources", stubbed);

/* EVERY READ A SCREEN MAKES, ANSWERED THE SAME WAY, WITHOUT NAMING ONE OF THEM.
 *
 * A screen's loading state and its failure state are properties of the screen rather than of any one resource: a
 * reading is outstanding while ANY of its reads is, and a refusal outranks an outstanding read. So the way to put
 * a screen into either state is to answer everything it asks for that way, and the way to keep that true when a
 * screen gains a ninth read is not to enumerate the eight.
 *
 * A LIST OF READS IS A SECOND COPY OF WHAT THE SCREEN FETCHES, and Settings alone makes six. These two handlers
 * therefore match the api prefix rather than a path, which is why they are here beside the specific stubs rather
 * than in one test file: the shell's own reads are passed AHEAD of them by the caller, because msw's first
 * matching handler wins.
 */
const API_READS = "/api/v1/*";

/** Every api read outstanding, so a screen renders whatever it renders while nothing has arrived. */
export const pendingReads = (): RequestHandler =>
  http.get(url(API_READS), async () => {
    await delay("infinite");
    return HttpResponse.json(null);
  });

/** Every api read refused with one problem document, so a screen renders its own failure surface. */
export const refusedReads = (problem: Problem = readUnavailable): RequestHandler =>
  http.get(url(API_READS), () => HttpResponse.json(problem, { status: problem.status }));

/* The api's own shape for a read it cannot serve: a 503 naming what is unavailable and what still works.
 * Written as a problem document because that is what the client narrows, and a failure surface renders
 * `problem.detail` verbatim. The type AND the title are the ones the api's 503 actually carries, read off
 * `DependencyUnavailable`: a double that answers a vocabulary the api has never held is a double of
 * nothing. Only the sentence is this file's own, because only the sentence is what a screen renders. */
export const readUnavailable: Problem = {
  type: "syncr:dependency-unavailable",
  title: "Dependency unavailable",
  status: 503,
  detail:
    "The api could not serve this read. Nothing was changed, and the plan already on screen is unaffected.",
};
