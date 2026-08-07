/* Rendering the Backlog screen, and the three reads it goes through.
 *
 * THE HANDLERS ARE KEYED BY PATH AND RECORD WHAT THEY WERE ASKED, because two of this screen's claims are about
 * the REQUEST rather than about the rendering: a filter has to reach the api, and the at-risk narrowing has to be
 * the server's. So the stub keeps every query string it was sent, which is what lets a test assert that pressing
 * a sort header changed nothing about the query and that choosing a filter changed it.
 *
 * THE BACKLOG'S ANSWER CAN CHANGE BETWEEN READS. `answerWith` replaces what the next read returns, which is how
 * the two cases the wave named are driven: an at-risk mark that moves while the list is open, and a task
 * completed somewhere else. Neither is a push: the api recomputes the marking on every read, and what makes the
 * screen read again is its own write. */

import { http, HttpResponse } from "msw";
import type { JsonBodyType } from "msw";

import { apiServer } from "../../../testing/apiServer";
import { renderSignedInAt } from "../../../testing/renderRoute";
import type { Areas } from "../../../api/hooks/useAreas";
import type { Backlog } from "../../../api/hooks/useBacklog";
import type { Settings } from "../../../api/hooks/useSettings";
import { buildAreas, buildBacklog, buildSettings } from "./fixtures";

const origin = window.location.origin;

export interface BacklogStub {
  /** Every query string the backlog was read with, in order. `""` for the unfiltered read. */
  readonly queries: string[];
  /** Every body the capture route was sent, parsed, in order. */
  readonly captured: unknown[];
  /** Every task the completion route was asked to complete, in order. */
  readonly completed: string[];
  /** What the NEXT read of the backlog answers with. */
  readonly answerWith: (next: Backlog) => void;
  /** What the next capture answers with instead of a 201: the status and the problem given. */
  readonly refuseCaptureWith: (status: number, problem: JsonBodyType) => void;
  readonly refuseCompletionWith: (status: number, problem: JsonBodyType) => void;
  /**
   * Hold every capture open until `releaseCapture` is called.
   *
   * A write's in-flight window is a state the screen holds for one round trip, so asserting anything about it
   * needs a response whose timing the test owns. Released before the test ends, so the invalidation that follows
   * is asserted rather than left running past the assertion.
   */
  readonly holdCapture: () => void;
  readonly releaseCapture: () => void;
}

export interface BacklogStubInput {
  readonly backlog?: Backlog;
  readonly areas?: Areas;
  readonly settings?: Settings;
}

export function stubBacklog(input: BacklogStubInput = {}): BacklogStub {
  const queries: string[] = [];
  const captured: unknown[] = [];
  const completed: string[] = [];
  let answered = input.backlog ?? buildBacklog();
  let captureRefusal: { status: number; problem: JsonBodyType } | null = null;
  let completionRefusal: { status: number; problem: JsonBodyType } | null = null;
  let held: Promise<void> | null = null;
  let release: (() => void) | null = null;

  apiServer.use(
    http.get(`${origin}/api/v1/areas`, () => HttpResponse.json(input.areas ?? buildAreas())),
    http.get(`${origin}/api/v1/settings`, () =>
      HttpResponse.json(input.settings ?? buildSettings()),
    ),
    http.get(`${origin}/api/v1/tasks`, ({ request }) => {
      queries.push(new URL(request.url).search.replace(/^\?/, ""));
      return HttpResponse.json(answered);
    }),
    http.post(`${origin}/api/v1/tasks`, async ({ request }) => {
      captured.push(await request.json().catch(() => null));
      if (held !== null) await held;
      if (captureRefusal !== null) {
        return HttpResponse.json(captureRefusal.problem, { status: captureRefusal.status });
      }
      return HttpResponse.json(answered.tasks[0] ?? null, { status: 201 });
    }),
    http.post(`${origin}/api/v1/tasks/:taskId/complete`, ({ params }) => {
      completed.push(String(params.taskId));
      if (completionRefusal !== null) {
        return HttpResponse.json(completionRefusal.problem, { status: completionRefusal.status });
      }
      return HttpResponse.json(answered.tasks[0] ?? null);
    }),
  );

  return {
    queries,
    captured,
    completed,
    answerWith: (next) => {
      answered = next;
    },
    refuseCaptureWith: (status, problem) => {
      captureRefusal = { status, problem };
    },
    refuseCompletionWith: (status, problem) => {
      completionRefusal = { status, problem };
    },
    holdCapture: () => {
      held = new Promise<void>((resolve) => {
        release = resolve;
      });
    },
    releaseCapture: () => {
      release?.();
      held = null;
      release = null;
    },
  };
}

/** The screen, rendered through the real route table at `/backlog`. */
export async function renderBacklog(input: BacklogStubInput = {}): Promise<BacklogStub> {
  const stub = stubBacklog(input);
  await renderSignedInAt("/backlog");
  return stub;
}
