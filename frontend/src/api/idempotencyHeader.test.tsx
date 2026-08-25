/* THE IDEMPOTENCY HEADER, ASSERTED ON EVERY WRITE THE POLICY KEYS AND ON THE ONE ROUTE THAT CARRIES NONE.
 *
 * THE SET IS THE FIVE WRITES WHOSE ROUTES READ A KEY -- the two on `usePinning` and three of the four on
 * `useWeekWrites` -- plus `/weeks/{iso_week}/tradeoffs`, whose route declares no key reader and is therefore sent
 * none. The writing layer (`useWrite`) owns both the name and the minting, so what each case holds is not which
 * constant a hook imported but what actually crossed the wire.
 *
 * THE HEADER AND ITS VALUE ARE SPELLED OUT HERE RATHER THAN IMPORTED, for the same reason its sibling
 * `sessionModeHeader.test.tsx` spells its own: a case that read the header through the writing layer's constant
 * would follow a rename of the wire contract rather than catch it. The value is held to the shape of a minted UUID,
 * which is what makes an empty string, a hoisted literal, or a forgotten mint fail rather than pass vacuously.
 *
 * ABSENT IS NOT ANY VALUE, and the two are told apart by recording both readings of every request, exactly as the
 * sibling does: whether the header was there at all, and what it carried. A client that sent the empty string would
 * satisfy a presence-only reading of nothing.
 *
 * THE WRITES ARE ISSUED BY MOUNTING THE HOOKS directly rather than by pressing the screen's controls: this file's
 * subject is what the writing layer puts on the wire, and whether the screen wires its controls to these hooks is
 * the week screen's own claim, asserted there. */

import { renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../testing/apiServer";
import { FreshCache } from "../testing/renderRoute";
import {
  BLOCK_LEETCODE,
  ISO_WEEK,
  TASK_ID,
  buildApproved,
  buildConflict,
  buildOperation,
  buildPin,
  buildPinned,
  monday,
} from "../routes/week/__tests__/fixtures";
import { usePinning, type Pinning } from "./hooks/usePins";
import { useWeekWrites, type WeekWrites } from "./hooks/useWeekWrites";
import type { WriteMethod } from "../testing/apiStub";

const HEADER = "Idempotency-Key";
const MINTED = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const PIN = buildPin();
const CONFLICT = buildConflict();
const WEEK = `/api/v1/weeks/${ISO_WEEK}`;

/** What one request said about idempotency: whether the header was there, and what it carried. */
interface Stated {
  readonly present: boolean;
  readonly value: string | null;
}

const ABSENT: Stated = { present: false, value: null };

function statedIn(request: Request): Stated {
  return { present: request.headers.has(HEADER), value: request.headers.get(HEADER) };
}

/** The two write hooks the week screen holds, mounted together so one render serves any case. */
interface ScreenWrites {
  readonly pinning: Pinning;
  readonly writes: WeekWrites;
}

function useScreenWrites(): ScreenWrites {
  return {
    pinning: usePinning(ISO_WEEK, 0),
    writes: useWeekWrites(ISO_WEEK),
  };
}

/**
 * One keyed write, as the screen's own hook issues it.
 *
 * `respond` is a call rather than a body because the statuses differ and one of them is a `204`, which may carry no
 * body at all.
 */
interface KeyedCase {
  readonly method: WriteMethod;
  readonly path: string;
  readonly respond: () => Response;
  readonly submit: (screen: ScreenWrites) => Promise<boolean>;
}

/* EVERY WRITE WHOSE ROUTE READS A KEY. A write added to either hook compiles silently until someone answers for it,
 * so this table is where the answer lands. */
const KEYED_WRITES = {
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
} satisfies Record<string, KeyedCase>;

/** The member names of the table, so a case is named by the hook member a failing case reports. */
type KeyedName = keyof typeof KEYED_WRITES;

/** The cases as a list. */
const CASES = (Object.keys(KEYED_WRITES) as KeyedName[]).map((name) => ({ name }));

/** The route a case drives, recording what every request it answered said about idempotency. */
function keysSentTo(name: KeyedName): {
  stated: Stated[];
  submit: (screen: ScreenWrites) => Promise<boolean>;
} {
  const write = KEYED_WRITES[name];
  const stated: Stated[] = [];
  apiServer.use(
    http[write.method](`${window.location.origin}${write.path}`, ({ request }) => {
      stated.push(statedIn(request));
      return write.respond();
    }),
  );
  return { stated, submit: (screen) => write.submit(screen) };
}

describe("every write whose route reads a key sends a freshly minted one", () => {
  it.each(CASES)("$name carries an Idempotency-Key", async ({ name }) => {
    const { stated, submit } = keysSentTo(name);

    const { result } = renderHook(() => useScreenWrites(), { wrapper: FreshCache });

    /* The write has to LAND. A refused request carries whatever header it carried, so a case that only read the
     * recorder would report a key on a request the api never accepted. */
    await expect(submit(result.current)).resolves.toBe(true);
    expect(stated).toHaveLength(1);
    expect(stated[0]?.present).toBe(true);
    expect(stated[0]?.value).toMatch(MINTED);
  });

  it("mints again per attempt, so two attempts never share a key", async () => {
    const { stated, submit } = keysSentTo("pin");

    const { result } = renderHook(() => useScreenWrites(), { wrapper: FreshCache });
    await submit(result.current);
    await submit(result.current);

    expect(stated).toHaveLength(2);
    expect(stated[0]?.value).toMatch(MINTED);
    expect(stated[1]?.value).toMatch(MINTED);
    expect(stated[0]?.value).not.toEqual(stated[1]?.value);
  });
});

describe("the route that reads no key is sent none", () => {
  /* `/weeks/{iso_week}/tradeoffs` declares no key reader, so anything sent there is ignored. Recording BOTH readings
   * keeps the absence honest: a client that resumed sending a dead header fails here rather than passing beside a
   * presence check nobody wrote. */
  it("the tradeoff request sends no Idempotency-Key", async () => {
    const stated: Stated[] = [];
    apiServer.use(
      http.post(`${window.location.origin}${WEEK}/tradeoffs`, ({ request }) => {
        stated.push(statedIn(request));
        return HttpResponse.json(buildOperation(), { status: 202 });
      }),
    );

    const { result } = renderHook(() => useScreenWrites(), { wrapper: FreshCache });

    await expect(
      result.current.writes.requestTradeoff.submit({ kind: "drop_item", targetId: TASK_ID }),
    ).resolves.toBe(true);
    expect(stated).toEqual([ABSENT]);
  });
});
