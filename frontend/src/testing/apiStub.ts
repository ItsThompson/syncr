/* The api double.
 *
 * msw rather than a stubbed global, because the client captures `fetch` when it is created and a
 * later stub would never be reached: intercepting at the network layer tests the real client,
 * the real request it builds, and the real response parsing.
 *
 * Handlers are keyed by request path, not by call order, so adding or reordering a request in a
 * component cannot break an unrelated test. */

import { delay, http, HttpResponse, type RequestHandler } from "msw";
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
