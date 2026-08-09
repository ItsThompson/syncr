/* THE SESSION-MODE HEADER, ASSERTED ON EVERY UNSAFE WRITE THE WEEK SCREEN CAN MAKE.
 *
 * ONE MIDDLEWARE ON THE ONE CLIENT DECIDES THIS, so every hook on the screen inherits it and no call site states it.
 * That is the right design and it is also what makes a single assertion insufficient cover: a guard that stops setting
 * the header stops it on every write at once, so a case driving one write would report one failure for a defect that
 * reaches all of them. Each write is therefore its own case, named by the member the screen calls.
 *
 * THE HEADER AND ITS VALUE ARE SPELLED OUT HERE RATHER THAN IMPORTED. The api reads a spelling off the request, so a
 * case that read the header through the client's own constant would follow a rename of the wire contract rather than
 * catch it.
 *
 * ABSENT IS NOT `false`, and the two are told apart by recording both readings of every request: whether the header
 * was there at all, and what it said. An assertion written over the value alone would be satisfied by a middleware
 * that sent `false` outside a session, which is the one spelling this client must never send.
 *
 * THE MODE IS OPENED BY THE URL rather than by calling the flag's setter, because "with the session open" is a state
 * of the product and the route is what declares it. The writes are then issued through the screen's own write hooks,
 * which is where the header has to arrive: the screen offers no control for one of them, so a case driven by pressing
 * a button could not reach it at all. */

import { renderHook, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../testing/apiServer";
import { FreshCache, renderAt } from "../testing/renderRoute";
import {
  BLOCK_LEETCODE,
  ISO_WEEK,
  LEETCODE,
  SESSION_PATH,
  TASK_ID,
  WEEK_PATH,
  buildApproved,
  buildConflict,
  buildOperation,
  buildPin,
  buildPinned,
  buildProposal,
  buildSession,
  buildVerdict,
  buildWeekView,
  installSessionRead,
  installWeekReads,
  monday,
} from "../routes/week/__tests__/fixtures";
import { client } from "./client";
import { usePinning } from "./hooks/usePins";
import { useWeekSolve } from "./hooks/useWeek";
import { useWeekWrites } from "./hooks/useWeekWrites";
import type { WriteMethod } from "../testing/apiStub";
import type { Pinning } from "./hooks/usePins";
import type { SolveRequest } from "./hooks/useWeek";
import type { WeekWrites } from "./hooks/useWeekWrites";
import type { Write } from "./hooks/useWrite";

const HEADER = "X-Syncr-Session-Mode";
const STATED_OPEN = "true";

const WEEK = `/api/v1/weeks/${ISO_WEEK}`;
const PIN = buildPin();
const CONFLICT = buildConflict();

/* A week nothing on screen asks for, which is what a read issued INSIDE the session is made against. The mode's own
 * payload is fetched before the route's effect declares the session, so a recorder on that read reports an absent
 * header whatever the middleware does with a safe method. */
const UNREAD_WEEK = "2026-W09";

/** What one request said about the session: whether the header was there, and what it carried. */
interface Stated {
  readonly present: boolean;
  readonly value: string | null;
}

const ABSENT: Stated = { present: false, value: null };
const OPEN: Stated = { present: true, value: STATED_OPEN };

function statedIn(request: Request): Stated {
  return { present: request.headers.has(HEADER), value: request.headers.get(HEADER) };
}

/** Every write hook the Week screen holds, mounted together so one render serves any case. */
interface ScreenWrites {
  readonly pinning: Pinning;
  readonly writes: WeekWrites;
  readonly solve: Write<SolveRequest>;
}

function useScreenWrites(): ScreenWrites {
  return {
    pinning: usePinning(ISO_WEEK, 0),
    writes: useWeekWrites(ISO_WEEK),
    solve: useWeekSolve(),
  };
}

/**
 * One unsafe write, as the screen's own hook issues it.
 *
 * `respond` is a call rather than a body because the statuses differ and one of them is a `204`, which may carry no
 * body at all: a single JSON answer for every case would be a shape the api cannot send.
 */
interface WeekWriteCase {
  readonly method: WriteMethod;
  readonly path: string;
  readonly respond: () => Response;
  readonly submit: (screen: ScreenWrites) => Promise<boolean>;
}

/** The members of `WeekWrites`, the two on `usePinning`, and the immediate solve the screen's own action asks for. */
type WeekWriteName = keyof WeekWrites | "pin" | "unpin" | "solve";

/* EVERY UNSAFE WRITE REACHABLE FROM THE WEEK SCREEN, keyed by the hook member the screen calls. `keyof WeekWrites`
 * exhausts that hook, so a member added to it is a type error here until this table covers it. */
const WEEK_WRITES = {
  pin: {
    method: "post",
    path: `${WEEK}/pins`,
    respond: () => HttpResponse.json(buildPinned(), { status: 201 }),
    submit: ({ pinning }) =>
      pinning.pin.submit({ blockId: BLOCK_LEETCODE, startMs: Date.parse(monday("09:15")) }),
  },
  unpin: {
    method: "delete",
    path: `${WEEK}/pins/${PIN.id}`,
    respond: () => new HttpResponse(null, { status: 204 }),
    submit: ({ pinning }) => pinning.unpin.submit({ pinId: PIN.id, blockId: BLOCK_LEETCODE }),
  },
  requestTradeoff: {
    method: "post",
    path: `${WEEK}/tradeoffs`,
    respond: () => HttpResponse.json(buildOperation(), { status: 202 }),
    submit: ({ writes }) => writes.requestTradeoff.submit({ kind: "drop_item", targetId: TASK_ID }),
  },
  approve: {
    method: "post",
    path: `${WEEK}/approve`,
    respond: () => HttpResponse.json(buildApproved(), { status: 201 }),
    submit: ({ writes }) => writes.approve.submit(undefined),
  },
  rejectMove: {
    method: "post",
    path: `${WEEK}/reject-block`,
    respond: () => HttpResponse.json(buildPinned(), { status: 201 }),
    submit: ({ writes }) => writes.rejectMove.submit({ blockId: BLOCK_LEETCODE }),
  },
  resolveConflict: {
    method: "post",
    path: `/api/v1/conflicts/${CONFLICT.id}/resolve`,
    respond: () =>
      HttpResponse.json(
        {
          conflict: buildConflict({ resolvedAt: monday("09:00"), resolution: "moved" }),
          operation: buildOperation(),
        },
        { status: 200 },
      ),
    submit: ({ writes }) =>
      writes.resolveConflict.submit({ conflictId: CONFLICT.id, resolution: "moved" }),
  },
  solve: {
    method: "post",
    path: `${WEEK}/solve`,
    respond: () => HttpResponse.json(buildOperation(), { status: 202 }),
    submit: ({ solve }) => solve.submit({ isoWeek: ISO_WEEK, isImmediate: true }),
  },
} satisfies Record<WeekWriteName, WeekWriteCase>;

/** The table as a list, each case carrying the member name a failing case should report. */
function listed(table: Readonly<Record<string, WeekWriteCase>>): {
  name: string;
  write: WeekWriteCase;
}[] {
  return Object.entries(table).map(([name, write]) => ({ name, write }));
}

const CASES = listed(WEEK_WRITES);

/** The case's own route, recording what every request it answered stated about the session. */
function record(write: WeekWriteCase): Stated[] {
  const stated: Stated[] = [];
  apiServer.use(
    http[write.method](`${window.location.origin}${write.path}`, ({ request }) => {
      stated.push(statedIn(request));
      return write.respond();
    }),
  );
  return stated;
}

/** A read of a week nothing on screen asks for, recording what it stated about the session. */
function recordRead(isoWeek: string): Stated[] {
  const stated: Stated[] = [];
  apiServer.use(
    http.get(`${window.location.origin}/api/v1/weeks/${isoWeek}`, ({ request }) => {
      stated.push(statedIn(request));
      return HttpResponse.json(buildWeekView({ isoWeek }));
    }),
  );
  return stated;
}

/** A week with a proposal and a verdict, so the screen and the mode both reach their ready state. */
function installReads(): void {
  installWeekReads(buildWeekView({ verdict: buildVerdict(), proposal: buildProposal() }));
}

/** The session, opened the way a reader opens it: at its URL, so the route's own effect declares the mode. */
async function openTheSession(): Promise<void> {
  installReads();
  installSessionRead(buildSession());
  renderAt(SESSION_PATH);
  await screen.findByLabelText("Weekly session");
}

/** The same screen with no mode in the URL, which is what a reader outside a session is looking at. */
async function openTheWeek(): Promise<void> {
  installReads();
  renderAt(WEEK_PATH);
  await screen.findByLabelText(`${LEETCODE} · Career`);
}

describe("with the session open, every unsafe write the Week screen can make states so", () => {
  it.each(CASES)("$name states that a session is open", async ({ write }) => {
    const stated = record(write);
    await openTheSession();

    const { result } = renderHook(() => useScreenWrites(), { wrapper: FreshCache });

    /* The write has to LAND. A refused request carries whatever header it carried, so a case that only read the
     * recorder would report the header on a request the api never accepted. */
    await expect(write.submit(result.current)).resolves.toBe(true);
    expect(stated).toEqual([OPEN]);
  });

  it("sends nothing at all on a read made while the session is open", async () => {
    /* THE READ IS ISSUED AFTER THE MODE IS ON SCREEN, which is what makes this the safe-method half of the guard
     * rather than a restatement of the flag's timing. The api resolves the header only where a verdict is recorded,
     * because its refusal for an unreadable value says nothing was changed, and that is meaningless on a read. */
    await openTheSession();
    const stated = recordRead(UNREAD_WEEK);

    await client.GET("/api/v1/weeks/{iso_week}", { params: { path: { iso_week: UNREAD_WEEK } } });

    expect(stated).toEqual([ABSENT]);
  });
});

describe("outside a session, none of those writes carries the header", () => {
  it.each(CASES)(
    "$name sends no header, which is not the same as sending `false`",
    async ({ write }) => {
      const stated = record(write);
      await openTheWeek();

      const { result } = renderHook(() => useScreenWrites(), { wrapper: FreshCache });

      await expect(write.submit(result.current)).resolves.toBe(true);
      expect(stated).toEqual([ABSENT]);
    },
  );
});
