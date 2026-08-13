/* THE ORDER SEVERAL PATHS WERE WRITTEN IN, WHICH IS WHAT A CLAIM ABOUT A SEQUENCE NEEDS.
 *
 * `recordingHandler` answers what ONE path was sent, which is enough for a claim about a body and cannot answer
 * one about an order: two handlers holding one body each cannot say which arrived first. A gesture that has to
 * issue exactly two requests, in one order, and exactly none of a third is a claim about the whole sequence, so
 * the sequence is what this records.
 *
 * THE THIRD PATH IS THE POINT. An absence asserted by leaving a route unstubbed is asserted against nothing: the
 * request would 404 or be reported unhandled, and a case reading "no pin was sent" from a handler that never
 * existed cannot tell a product that stopped sending one from a product that never could. So a path a gesture
 * must NOT touch is stubbed like the others, answers as though it would have worked, and is asserted at zero.
 *
 * ONE HANDLER PER PATH, ALL WRITING TO ONE LIST, so adding a path to a case cannot change what another one
 * records. The pattern is kept beside the concrete URL because they answer different questions: the pattern is
 * what an ORDER is read in, and the URL is what says which resource a request was addressed to. */

import { http, HttpResponse, type RequestHandler } from "msw";

import { apiServer } from "./apiServer";
import type { StubbedResponse, WriteMethod } from "./apiStub";

/** One unsafe request the api received. */
export interface RecordedWrite {
  readonly method: WriteMethod;
  /** The path pattern the handler was declared with, which is stable across the identifiers in it. */
  readonly pattern: string;
  /** The path the request actually went to, which is what names the resource it addressed. */
  readonly path: string;
  /** The parsed body, or null for a method that carries none. */
  readonly body: unknown;
}

/** A write path a case stubs: which method, which pattern, and what it answers. */
export interface WriteStub {
  readonly method: WriteMethod;
  readonly path: string;
  /** What it answers. A function for a case whose second attempt has to be answered differently from its first. */
  readonly answer: StubbedResponse | (() => StubbedResponse);
}

export interface WriteLog {
  /** Every write the api received, in arrival order. */
  readonly wrote: readonly RecordedWrite[];
  /** `["POST /api/v1/tasks", "PUT /api/v1/tasks/:taskId/preference"]`: the reading an order is asserted in. */
  readonly sequence: () => readonly string[];
  /** How many writes went to one stubbed pattern, which is how an absence is read off a handler that could fire. */
  readonly countOf: (method: WriteMethod, pattern: string) => number;
}

/** The stubs installed, sharing one log. Later than any read stub the case installed, so these answer first. */
export function recordWrites(stubs: readonly WriteStub[]): WriteLog {
  const wrote: RecordedWrite[] = [];
  const handlers: RequestHandler[] = stubs.map((stub) =>
    http[stub.method](`${window.location.origin}${stub.path}`, async ({ request }) => {
      wrote.push({
        method: stub.method,
        pattern: stub.path,
        path: new URL(request.url).pathname,
        body: await request.json().catch(() => null),
      });
      const answer = typeof stub.answer === "function" ? stub.answer() : stub.answer;
      return HttpResponse.json(answer.body ?? null, { status: answer.status });
    }),
  );
  apiServer.use(...handlers);

  return {
    wrote,
    sequence: () => wrote.map((one) => `${one.method.toUpperCase()} ${one.pattern}`),
    countOf: (method, pattern) =>
      wrote.filter((one) => one.method === method && one.pattern === pattern).length,
  };
}
