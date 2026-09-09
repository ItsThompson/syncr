import assert from "node:assert/strict";
import { describe, it } from "node:test";

import type { ApiClient } from "../api/client.ts";
import type { Operation } from "../api/schemas.ts";
import { operation } from "./week.ts";

const buildOperation = (overrides: Partial<Operation> = {}): Operation => ({
  attempt: 1,
  error: null,
  finishedAt: null,
  id: "op-1",
  inputVersion: null,
  kind: "solve",
  resultRevisionId: null,
  scheduledFor: "2026-01-01T00:00:00Z",
  startedAt: null,
  statement: "solved",
  status: "succeeded",
  supersededBy: null,
  target: { isoWeek: "2026-W01", sourceId: null },
  ...overrides,
});

/** A client whose only exercised method is `attempt`, which `operation` is the sole reader of. */
const clientWithAttempt = (attempt: ApiClient["attempt"]): ApiClient => ({
  baseUrl: "http://test.invalid",
  sessionCookie: "test",
  get: () => Promise.reject(new Error("get not used")),
  post: () => Promise.reject(new Error("post not used")),
  put: () => Promise.reject(new Error("put not used")),
  patch: () => Promise.reject(new Error("patch not used")),
  del: () => Promise.reject(new Error("del not used")),
  attempt,
});

/** An `attempt` that answers one status and body, whatever the caller's type parameter is. */
const attemptReturning =
  (status: number, body: unknown): ApiClient["attempt"] =>
  async <T>() => ({ status, body: body as T, headers: new Headers() });

const rejectsWith = (promise: Promise<unknown>, message: string): Promise<void> =>
  assert.rejects(promise, (error: unknown) => error instanceof Error && error.message === message);

describe("operation", () => {
  it("returns the body on 200", async () => {
    const client = clientWithAttempt(attemptReturning(200, buildOperation()));
    const result = await operation(client, "op-1");
    assert.equal(result.id, "op-1");
  });

  it("fails on 404 through the ordinary non-200 demand", async () => {
    const client = clientWithAttempt(attemptReturning(404, { detail: "missing" }));
    await rejectsWith(
      operation(client, "op-1"),
      "GET /api/v1/operations/op-1 answered 404: no type missing",
    );
  });

  it("fails on 500 through the ordinary non-200 demand", async () => {
    const client = clientWithAttempt(attemptReturning(500, { detail: "boom" }));
    await rejectsWith(
      operation(client, "op-1"),
      "GET /api/v1/operations/op-1 answered 500: no type boom",
    );
  });
});
