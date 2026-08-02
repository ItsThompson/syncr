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

/** A path whose request never completes, standing in for an unreachable api. */
export function unreachableHandler(path: string): RequestHandler {
  return http.get(url(path), () => HttpResponse.error());
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
  body: { status: "ready", checks: {} },
};

export const notReadyResponse: StubbedResponse = {
  status: 503,
  body: { status: "not_ready", checks: { migrations: { ok: false, detail: "head not applied" } } },
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
