/* One day's ledger, and the three writes the Today screen makes on it.
 *
 * FOUR HOOKS RATHER THAN ONE, because a read and three writes have four different shapes. What they share
 * is the key: every one of these writes changes the day on screen and names `dayKey(date)`, so a mutation
 * invalidates precisely rather than revalidating a screen's worth of reads that did not change.
 *
 * TWO OF THE THREE WRITES ARE OPTIMISTIC, AND THE THIRD IS NOT, which is the rule rather than an
 * inconsistency. Recording an outcome and confirming a day have answers this client can derive
 * completely, so `dayProjection` derives them and the row redraws before the response lands. A backfill's
 * answer is how many days the server found outstanding, which the client cannot know: it holds the count
 * the last read reported and not which dates produced it. So a backfill waits, and what it states
 * afterwards is the response's own figures.
 *
 * A CHANGE AND ITS UNDO ARE BOTH FUNCTIONS OF THE LATEST DAY, never of a snapshot. A refused write puts
 * back the rows it changed and leaves every other row as it now stands, so two writes in flight compose:
 * restoring a snapshot would drop a change a peer had applied to another row in between. It is also why the
 * undo does not refetch: an api that refused a write is an api a second request may not reach either, and
 * reverting over the network would replace a whole ledger with an error surface over one refused row.
 *
 * A RECORDING'S REFUSAL CARRIES THE ROW IT BELONGS TO, which is why it does not use `useWrite`: that hook
 * holds one refusal for one subject, and a ledger has as many subjects as it has rows. Volume one is
 * inline at the thing it concerns, so the notice has to know which thing that was.
 *
 * THE WEEK COMES FROM THE DATE. A block id is a digest of the week and the content it holds, so the week
 * cannot be read back out of the id, and the ledger is addressed by date. */

import { useState } from "react";
import useSWR, { useSWRConfig, type ScopedMutator } from "swr";

import { client } from "../client";
import { dayKey } from "../keys";
import {
  outcomesOf,
  unansweredBlockIds,
  withConfirmedDay,
  withRecordedOutcome,
  withRestoredOutcomes,
  type Day,
} from "./dayProjection";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export { stateOf } from "./dayProjection";
export type { Day, DayRow, Outcome, OutcomeState } from "./dayProjection";
export type Backfill = components["schemas"]["ConfirmRangeResponse"];
export type OutcomeBody = components["schemas"]["OutcomeRequest"];

/** What the reader said happened to one block, and which block it was. */
export interface OutcomeDraft {
  readonly blockId: string;
  readonly outcome: OutcomeBody;
}

/** Which past days a backfill settles, both dates included. */
export interface BackfillRange {
  readonly from: string;
  readonly to: string;
}

async function readDay(date: string): Promise<Day> {
  return read(() => client.GET("/api/v1/days/{date}", { params: { path: { date } } }));
}

export function useDay(date: string): Resource<Day> {
  return toResource(useSWR<Day, Problem>(dayKey(date), () => readDay(date)));
}

/** What a write does to the day on screen, and how it is undone when the api refuses it. */
interface DayChange {
  readonly project: (latest: Day) => Day;
  readonly restore: (latest: Day) => Day;
}

/**
 * A write that shows its answer before the api gives it, and puts back what it changed when refused.
 *
 * `change` is null where the caller has no day to project onto, which is every state but `ready`. The
 * screen renders no outcome control until the ledger has arrived, so the write is then an ordinary one
 * rather than one projecting onto a day it invented.
 */
async function optimistically(
  mutate: ScopedMutator,
  date: string,
  change: DayChange | null,
  send: () => Promise<Problem | null>,
): Promise<Problem | null> {
  const key = dayKey(date);
  const applied = (step: (latest: Day) => Day) =>
    mutate<Day>(key, (latest) => (latest === undefined ? latest : step(latest)), {
      revalidate: false,
    });

  if (change !== null) await applied(change.project);

  const refusal = await send();
  if (refusal !== null) {
    if (change !== null) await applied(change.restore);
    return refusal;
  }

  await mutate(key);
  return null;
}

/** A refused recording, and the row it was refused on, so the notice lands where the reader was. */
export interface OutcomeRefusal {
  readonly blockId: string;
  readonly problem: Problem;
}

export interface OutcomeRecording {
  /** True when the outcome was recorded. False leaves `refusal` naming the row and the reason. */
  readonly record: (draft: OutcomeDraft) => Promise<boolean>;
  readonly refusal: OutcomeRefusal | null;
}

/**
 * Recording what happened to one block.
 *
 * The optimistic row is the one the api will answer with: the state the reader chose, the figure that
 * state carries, the block's own start as the instant it occurred at, and the day's settled instant
 * unchanged, because recording an outcome does not confirm a day.
 */
export function useOutcomeRecording(date: string, day: Day | null): OutcomeRecording {
  const { mutate } = useSWRConfig();
  const [refusal, setRefusal] = useState<OutcomeRefusal | null>(null);

  const record = async (draft: OutcomeDraft): Promise<boolean> => {
    const before = day === null ? null : outcomesOf(day, [draft.blockId]);
    const refused = await optimistically(
      mutate,
      date,
      before === null
        ? null
        : {
            project: (latest) => withRecordedOutcome(latest, draft.blockId, draft.outcome),
            restore: (latest) => withRestoredOutcomes(latest, before),
          },
      () =>
        apply(() =>
          client.PUT("/api/v1/blocks/{block_id}/outcome", {
            params: { path: { block_id: draft.blockId } },
            body: draft.outcome,
          }),
        ),
    );
    setRefusal(refused === null ? null : { blockId: draft.blockId, problem: refused });
    return refused === null;
  };

  return { record, refusal };
}

/**
 * Confirming the day, which converts presumption into record for every block of it.
 *
 * The projected instant is the client's and the stored one is the server's: they differ by the round
 * trip, and the invalidation that follows replaces the projection with what was stored.
 *
 * The undo names the blocks this call would stamp, which are the ones carrying no instant, so a refusal
 * leaves a row someone answered for in between exactly as it now stands.
 */
export function useDayConfirmation(date: string, day: Day | null): Write<void> {
  const { mutate } = useSWRConfig();

  return useWrite(() => {
    const before = day === null ? null : outcomesOf(day, unansweredBlockIds(day));
    return optimistically(
      mutate,
      date,
      before === null
        ? null
        : {
            project: (latest) => withConfirmedDay(latest, new Date().toISOString()),
            restore: (latest) => withRestoredOutcomes(latest, before),
          },
      () => apply(() => client.POST("/api/v1/days/{date}/confirm", { params: { path: { date } } })),
    );
  });
}

export interface BackfillWrite extends Write<BackfillRange> {
  /** What the last backfill settled, or null while none has been asked for. */
  readonly settled: Backfill | null;
}

/** Confirming several past days in one call, and what the api says it settled. */
export function useBackfill(date: string): BackfillWrite {
  const { mutate } = useSWRConfig();
  const [settled, setSettled] = useState<Backfill | null>(null);

  const write = useWrite(async (range: BackfillRange) => {
    /* The body is captured from inside `apply` rather than returned by it. `request.ts` offers two answer
     * shapes, one that throws and one that discards the body, and a third belongs there rather than here:
     * it is shared infrastructure, and one write wanting a response body is not yet a pattern. */
    let answered: Backfill | undefined;
    const refusal = await apply(async () => {
      const result = await client.POST("/api/v1/days/confirm-range", { body: range });
      answered = result.data;
      return result;
    });
    if (refusal !== null) return refusal;

    setSettled(answered ?? null);
    await mutate(dayKey(date));
    return null;
  });

  return { ...write, settled };
}
