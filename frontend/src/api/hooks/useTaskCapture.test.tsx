/* THE TWO WRITES ONE CONFIRM SENDS: which requests, in which order, and which of them a refusal belongs to.
 *
 * THE SEQUENCE IS ASSERTED WHOLE RATHER THAN PER PATH, because the claim is about a gesture: exactly one capture,
 * then exactly one preference on the task it created, and exactly no pin. Counting the two that must happen would
 * leave the third free to happen too, and a pin is not a smaller version of a preference -- it is a hard
 * constraint on the plan of record where a preferred window is a cost the solver trades off. So the pin route is
 * stubbed, answers as though it would have worked, and is read at zero.
 *
 * THE SECOND REQUEST'S ADDRESS IS THE FIRST'S ANSWER, so the case answers the capture with an identifier that is
 * in neither the request nor this file's other constants: a PUT that went anywhere else is then visible rather
 * than accidentally right.
 *
 * A REFUSED PREFERENCE MUST NOT LOSE THE TASK, and what a hook can say about that is that the capture was sent
 * once, was not sent again, and the list was re-read: the task is in the reader's backlog whatever the second
 * write did. */

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { countedHandler, type StubbedResponse } from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import { recordWrites, type WriteLog } from "../../testing/writeLog";
import { useBacklog } from "./useBacklog";
import { useTaskCapture, type TaskCapture } from "./useTaskCapture";
import type { Problem } from "../../contract";

const AREA = "3f1b7a3c-0001-4c8e-9a11-0000000000a1";
/* The identifier the api MINTS, which is what the second request has to be addressed to. Nothing else in this
   file carries it, so a PUT built from anything but the capture's own answer goes somewhere visible. */
const MINTED_TASK = "b41d9e70-77c5-4a6e-9a0f-2c7e5d8b1f34";
const ISO_WEEK = "2026-W07";

const CAPTURE_PATH = "/api/v1/tasks";
const PREFERENCE_PATH = "/api/v1/tasks/:taskId/preference";
const PINS_PATH = "/api/v1/weeks/:isoWeek/pins";

const BACKLOG = { header: { openCount: 1, atRiskCount: 0 }, tasks: [] as unknown[] };

const THE_TASK: TaskCapture["task"] = {
  areaId: AREA,
  title: "Kontron take-home",
  estimateMinutes: 60,
  minChunkMinutes: 15,
  deadline: null,
  priority: "normal",
  splittable: true,
};

/** The window an activated slot resolves to in the reader's own zone: two wall times, no date and no zone. */
const THE_WINDOW = { start: "14:00", end: "15:00" };

const REFUSAL: Problem = {
  type: "syncr:validation-failed",
  title: "Validation failed",
  status: 422,
  detail: "One or more members were refused.",
  errors: [{ field: "windows", message: "must land on the quarter hour" }],
};

interface Sent {
  readonly log: WriteLog;
  /** How many times the backlog was read, so the re-read after the pair is observable. */
  readonly reads: () => number;
}

/**
 * The three write paths of this gesture, with the capture and the preference answering what the case asked for.
 *
 * The backlog read has a subscriber of its own, because SWR does not read a key nothing is subscribed to: a count
 * taken without one is pinned to zero whatever the write invalidates.
 */
function stubTheWrites(
  capture: StubbedResponse | (() => StubbedResponse),
  preference: StubbedResponse | (() => StubbedResponse),
): Sent {
  const list = countedHandler(CAPTURE_PATH, { status: 200, body: BACKLOG });
  apiServer.use(list.handler);
  const log = recordWrites([
    { method: "post", path: CAPTURE_PATH, answer: capture },
    { method: "put", path: PREFERENCE_PATH, answer: preference },
    /* The route this gesture must never touch, stubbed so that the absence is read off a handler that could
       have answered. It answers what a real pin answers, so a product that sent one would get a plausible reply
       and the case would still see it. */
    { method: "post", path: PINS_PATH, answer: { status: 201, body: {} } },
  ]);
  return { log, reads: list.count };
}

const CAPTURED: StubbedResponse = { status: 201, body: { id: MINTED_TASK } };
const DECLARED: StubbedResponse = { status: 200, body: { owner: {}, declared: {}, effective: {} } };

function theCapture() {
  return renderHook(() => ({ read: useBacklog(), write: useTaskCapture() }), {
    wrapper: FreshCache,
  }).result;
}

describe("a confirm that carries a preferred window", () => {
  it("captures the task, then declares its preference, and pins nothing", async () => {
    const sent = stubTheWrites(CAPTURED, DECLARED);
    const capture = theCapture();
    await waitFor(() => {
      expect(capture.current.read.status).toBe("ready");
    });

    const outcome = await capture.current.write.submit({
      task: THE_TASK,
      preferredWindow: THE_WINDOW,
    });

    expect(outcome).toEqual({ refused: null, problem: null });
    expect(sent.log.sequence()).toEqual([`POST ${CAPTURE_PATH}`, `PUT ${PREFERENCE_PATH}`]);
    expect(sent.log.countOf("post", PINS_PATH)).toBe(0);
  });

  /* THE STRENGTH IS THE WHOLE DIFFERENCE BETWEEN A WINDOW AND A CONSTRAINT, so the body is asserted whole: a
     member added to it is a member nobody decided, and `strong` costs an order of magnitude more to violate. */
  it("declares the window at soft, with no ideal session length, on the task the api minted", async () => {
    const sent = stubTheWrites(CAPTURED, DECLARED);
    const capture = theCapture();

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    expect(sent.log.wrote.at(1)).toEqual({
      method: "put",
      pattern: PREFERENCE_PATH,
      path: `/api/v1/tasks/${MINTED_TASK}/preference`,
      body: { windows: [THE_WINDOW], strength: "soft", preferredDurationMinutes: null },
    });
  });

  it("sends the capture the caller built, unchanged and carrying no preference member", async () => {
    const sent = stubTheWrites(CAPTURED, DECLARED);
    const capture = theCapture();

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    expect(sent.log.wrote.at(0)?.body).toEqual(THE_TASK);
  });

  it("reads the list again once both writes have answered", async () => {
    const sent = stubTheWrites(CAPTURED, DECLARED);
    const capture = theCapture();
    await waitFor(() => {
      expect(capture.current.read.status).toBe("ready");
    });
    expect(sent.reads()).toBe(1);

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    await waitFor(() => {
      expect(sent.reads()).toBe(2);
    });
  });
});

describe("a confirm that carries no window", () => {
  it("captures the task and declares nothing", async () => {
    const sent = stubTheWrites(CAPTURED, DECLARED);
    const capture = theCapture();

    const outcome = await capture.current.write.submit({ task: THE_TASK, preferredWindow: null });

    expect(outcome).toEqual({ refused: null, problem: null });
    expect(sent.log.sequence()).toEqual([`POST ${CAPTURE_PATH}`]);
  });

  it("reads the list again, because the task is in it", async () => {
    const sent = stubTheWrites(CAPTURED, DECLARED);
    const capture = theCapture();
    await waitFor(() => {
      expect(capture.current.read.status).toBe("ready");
    });

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: null });

    await waitFor(() => {
      expect(sent.reads()).toBe(2);
    });
  });
});

describe("a capture the api refuses", () => {
  it("names the task as the write that did not land, and declares nothing", async () => {
    const sent = stubTheWrites({ status: 422, body: REFUSAL }, DECLARED);
    const capture = theCapture();

    const outcome = await capture.current.write.submit({
      task: THE_TASK,
      preferredWindow: THE_WINDOW,
    });

    expect(outcome).toEqual({ refused: "task", problem: REFUSAL });
    expect(sent.log.sequence()).toEqual([`POST ${CAPTURE_PATH}`]);
  });

  it("keeps the refusal, so the form that asked can render it at the members it names", async () => {
    stubTheWrites({ status: 422, body: REFUSAL }, DECLARED);
    const capture = theCapture();

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    await waitFor(() => {
      expect(capture.current.write.problem?.errors).toEqual(REFUSAL.errors);
    });
  });

  /* NOTHING WAS CREATED, so there is no list to re-read: a refused capture leaves the reader's own backlog exactly
     as it was, and reading it again would say something moved. */
  it("does not read the list again", async () => {
    const sent = stubTheWrites({ status: 422, body: REFUSAL }, DECLARED);
    const capture = theCapture();
    await waitFor(() => {
      expect(capture.current.read.status).toBe("ready");
    });

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    expect(sent.reads()).toBe(1);
  });
});

describe("a preference the api refuses", () => {
  it("names the preference as the write that did not land", async () => {
    stubTheWrites(CAPTURED, { status: 422, body: REFUSAL });
    const capture = theCapture();

    const outcome = await capture.current.write.submit({
      task: THE_TASK,
      preferredWindow: THE_WINDOW,
    });

    expect(outcome).toEqual({ refused: "preference", problem: REFUSAL });
  });

  /* THE TASK IS NOT LOST AND IS NOT SENT TWICE. It was created, so the honest answer is a list that holds it and
     a capture that happened once: a retry of the pair would put a second identical task in the backlog. */
  it("leaves the task captured once and reads the list that now holds it", async () => {
    const sent = stubTheWrites(CAPTURED, { status: 422, body: REFUSAL });
    const capture = theCapture();
    await waitFor(() => {
      expect(capture.current.read.status).toBe("ready");
    });

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    expect(sent.log.countOf("post", CAPTURE_PATH)).toBe(1);
    expect(sent.log.sequence()).toEqual([`POST ${CAPTURE_PATH}`, `PUT ${PREFERENCE_PATH}`]);
    await waitFor(() => {
      expect(sent.reads()).toBe(2);
    });
  });

  it("keeps the refusal the preference route answered, and pins nothing in its place", async () => {
    const sent = stubTheWrites(CAPTURED, { status: 422, body: REFUSAL });
    const capture = theCapture();

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    await waitFor(() => {
      expect(capture.current.write.problem?.detail).toBe(REFUSAL.detail);
    });
    expect(sent.log.countOf("post", PINS_PATH)).toBe(0);
  });
});

describe("a confirm after one that was refused", () => {
  /* The refusal stands until an attempt lands, which is what lets a form keep it on screen while the reader fixes
     the member it names. A capture that landed whole has nothing left to state. */
  it("clears the refusal the last one was answered with", async () => {
    let preference: StubbedResponse = { status: 422, body: REFUSAL };
    stubTheWrites(CAPTURED, () => preference);
    const capture = theCapture();

    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });
    await waitFor(() => {
      expect(capture.current.write.problem).not.toBeNull();
    });
    preference = DECLARED;
    await capture.current.write.submit({ task: THE_TASK, preferredWindow: THE_WINDOW });

    await waitFor(() => {
      expect(capture.current.write.problem).toBeNull();
    });
  });
});

describe("the pin route this gesture never uses", () => {
  /* THE CONTROL ON EVERY ZERO ABOVE. An absence read off a handler that cannot answer is not a reading, so this
     drives the same stub with a request of its own and reads one: the counter fires when something reaches it,
     which is what makes the zeros mean the product sent nothing. */
  it("is stubbed and counts a request that reaches it", async () => {
    const sent = stubTheWrites(CAPTURED, DECLARED);

    await fetch(`${window.location.origin}/api/v1/weeks/${ISO_WEEK}/pins`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ blockId: "b1", start: "2026-02-11T14:00:00+00:00" }),
    });

    expect(sent.log.countOf("post", PINS_PATH)).toBe(1);
  });
});
