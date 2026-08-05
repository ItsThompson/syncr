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
 * THE REVERT IS THE DAY THE ROW WAS RENDERED FROM, not a refetch. A refused write leaves the api's own
 * sentence beside the row, and a revert that had to reach the network would fail a second time exactly
 * when the api is unreachable, replacing a whole ledger with an error surface over one refused row.
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
import { withConfirmedDay, withRecordedOutcome, type Day } from "./dayProjection";
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

/**
 * A write that shows its answer before the api gives it, and puts the day back when it is refused.
 *
 * `current` is null where the caller has no day to project onto, which is every state but `ready`. The
 * screen renders no outcome control until the ledger has arrived, so the write is then an ordinary one
 * rather than one projecting onto a day it invented.
 */
async function optimistically(
  mutate: ScopedMutator,
  date: string,
  current: Day | null,
  projected: Day | null,
  send: () => Promise<Problem | null>,
): Promise<Problem | null> {
  const key = dayKey(date);
  if (projected !== null) await mutate(key, projected, { revalidate: false });

  const refusal = await send();
  if (refusal !== null) {
    if (current !== null) await mutate(key, current, { revalidate: false });
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
    const refused = await optimistically(
      mutate,
      date,
      day,
      day === null ? null : withRecordedOutcome(day, draft.blockId, draft.outcome),
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
 */
export function useDayConfirmation(date: string, day: Day | null): Write<void> {
  const { mutate } = useSWRConfig();

  return useWrite(() =>
    optimistically(
      mutate,
      date,
      day,
      day === null ? null : withConfirmedDay(day, new Date().toISOString()),
      () => apply(() => client.POST("/api/v1/days/{date}/confirm", { params: { path: { date } } })),
    ),
  );
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
