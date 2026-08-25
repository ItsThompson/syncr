/* PINS, AND THE LIVE VERDICT A PIN ANSWERS WITH.
 *
 * THE WRITE IS OPTIMISTIC AND THAT IS SAFE FOR ONE REASON ONLY: the server's pin placement is exactly what was
 * requested. So the block moves locally and takes the pin glyph on the same redraw the request goes out on, and
 * nothing else moves. A solve's output is not predictable, so the unpinned remainder is left alone until the solve
 * lands.
 *
 * EVERY PIN SENDS AN `Idempotency-Key`. A retried pin must not become two pins, and a pin is a training label: two
 * rows for one gesture would teach the learning layer a preference the reader stated once. The header's name and its
 * minting live in the writing layer (`useWrite`), which hands them to every keyed write; nothing about this route
 * states either.
 *
 * A RESPONSE FOR AN OLDER INPUT VERSION IS DISCARDED. Two pins in quick succession can answer out of order, and the
 * verdict of the earlier one describes inputs the week has moved past: applying it would show a shortfall that has
 * already been superseded, and the reader would be reading a stale refusal beside a fresh plan. The version is the
 * verdict's own `inputVersion`, which is the counter AFTER the pin bumped it.
 *
 * THE LATEST VERSION IS A REF RATHER THAN STATE, deliberately: it gates whether a response is applied, and gating on
 * state would mean a second response arriving in the same tick read the value the first one had not yet committed. */

import { useCallback, useRef, useState } from "react";
import { useSWRConfig } from "swr";

import { client } from "../client";
import { weekKey } from "../keys";
import { answered, apply } from "./request";
import { withPinAt, withPinReleased } from "./pinProjection";
import { idempotentHeaders, useWrite, type Write } from "./useWrite";
import type { Operation } from "../events";
import type { WeekView } from "./useWeek";
import type { components } from "../schema";
import type { Problem } from "../../contract";

type Verdict = components["schemas"]["VerdictResponse"];

export interface PinRequest {
  readonly blockId: string;
  /** Where the block now begins, as an instant. Its length is unchanged: a drag moves and does not resize. */
  readonly startMs: number;
}

export interface UnpinRequest {
  readonly pinId: string;
  /** The block the pin held, so the glyph can go on the same redraw the request goes out on. */
  readonly blockId: string;
}

/** What the last accepted pin response said about the week, or null while none has been accepted. */
export interface LiveVerdict {
  readonly verdict: Verdict;
  readonly operation: Operation;
  readonly inputVersion: number;
}

export interface Pinning {
  readonly pin: Write<PinRequest>;
  readonly unpin: Write<UnpinRequest>;
  /** The verdict, the operation and the version the last ACCEPTED response carried. */
  readonly live: LiveVerdict | null;
  /** The last refusal from either write, so one notice renders whichever failed. */
  readonly problem: Problem | null;
}

/**
 * Pinning for one week.
 *
 * `seedVersion` is the week's own `inputVersion` from the last read. Without it the first response of a session
 * would be accepted whatever version it named, which is only wrong in the case that matters: a tab left open while
 * another one edited.
 *
 * `onOperation` is how the THIRD member of the response is consumed. A pin answers with the solve it asked for or the
 * one it joined, and that answer is a whole event earlier than any read: handing it to the operation hook is what
 * makes the plan currency say `solving` on the same redraw as the pin rather than when the first event arrives.
 */
export function usePinning(
  isoWeek: string,
  seedVersion: number,
  onOperation?: (operation: Operation) => void,
): Pinning {
  const { mutate } = useSWRConfig();
  const [live, setLive] = useState<LiveVerdict | null>(null);
  const latestVersion = useRef(seedVersion);
  if (seedVersion > latestVersion.current) latestVersion.current = seedVersion;

  const accept = useCallback((next: LiveVerdict): boolean => {
    if (next.inputVersion < latestVersion.current) return false;
    latestVersion.current = next.inputVersion;
    setLive(next);
    return true;
  }, []);

  const pin = useWrite(async ({ blockId, startMs }: PinRequest) => {
    /* The optimistic frame goes in BEFORE the request, and stays: it is what makes the pin one redraw. */
    await mutate(
      weekKey(isoWeek),
      (held?: WeekView) => (held === undefined ? held : withPinAt(held, blockId, startMs)),
      {
        revalidate: false,
      },
    );

    const { body, problem } = await answered(() =>
      client.POST("/api/v1/weeks/{iso_week}/pins", {
        params: { path: { iso_week: isoWeek } },
        headers: idempotentHeaders(),
        body: { blockId, start: new Date(startMs).toISOString() },
      }),
    );
    if (problem !== null) {
      /* The plan of record never held the optimistic placement, so the honest recovery is to read it again. */
      await mutate(weekKey(isoWeek));
      return problem;
    }
    accept({
      verdict: body.verdict,
      operation: body.operation,
      inputVersion: body.verdict.inputVersion,
    });
    onOperation?.(body.operation);
    return null;
  });

  const unpin = useWrite(async ({ pinId, blockId }: UnpinRequest) => {
    await mutate(
      weekKey(isoWeek),
      (held?: WeekView) => (held === undefined ? held : withPinReleased(held, blockId)),
      {
        revalidate: false,
      },
    );
    const refusal = await apply(() =>
      client.DELETE("/api/v1/weeks/{iso_week}/pins/{pin_id}", {
        params: { path: { iso_week: isoWeek, pin_id: pinId } },
        headers: idempotentHeaders(),
      }),
    );
    /* Either way the week is read again: a release changes the plan the next solve produces, and a refusal means the
     * pin is still there. The removal answers 204 and carries no verdict, so there is nothing to accept. */
    await mutate(weekKey(isoWeek));
    return refusal;
  });

  return { pin, unpin, live, problem: pin.problem ?? unpin.problem };
}
