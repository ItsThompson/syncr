/* THE OPERATION LIFECYCLE. One hook over push, polling and supersession chains.
 *
 * THE DEEP MODULE ON THE FRONTEND. What a caller sees is an operation, a word for whether the plan is current, and
 * a failure to state. What it hides is the seed, the SSE subscription, the interval that engages only when the push
 * connection is down, and the chain a superseded solve is followed along.
 *
 * `superseded` IS FOLLOWED, NEVER SURFACED. It is the expected outcome of editing quickly -- a second pin displaces
 * the solve the first one asked for -- so showing it as a failure would make normal use look broken. The successor's
 * id is on the record, so the hook re-points at it and keeps waiting. A chain of any length is the same rule applied
 * again, which is why nothing here counts the hops.
 *
 * `succeeded` INVALIDATES THE WEEK KEY AND NOTHING ELSE. ONE refetch, ONE redraw. The event carries no plan
 * document by design, so the read model has one transport and the grid cannot be drawn from two.
 *
 * `failed` KEEPS THE PREVIOUS PLAN RENDERED. The plan of record did not change: a solve that failed wrote nothing,
 * so the honest rendering is the plan the reader already had, plus a notice at panel volume saying it is not
 * current.
 *
 * POLLING IS A FALLBACK AND NOT A SECOND CHANNEL. It engages only while the push connection is not open and only
 * while an operation is non-terminal, and it is SWR's own `refreshInterval` rather than an interval this module
 * runs: reconnection returns to push by the key's condition going false.
 *
 * CURRENCY IS THE SERVER'S FIGURE, QUALIFIED BY WHAT THIS CLIENT KNOWS AND THE LAST READ DID NOT. `readings
 * .planCurrency` is derived server-side so the strip and the pie review cannot disagree, and it is the base here.
 * The one thing it cannot know is an operation created by a mutation that answered AFTER that read: between a pin
 * and its solve landing, the read still says `current` while a solve is running. Both readings are the same
 * function of the same operation state, so qualifying is not a second arithmetic -- it is the same one, one event
 * ahead. */

import { useCallback, useState } from "react";
import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { operationKey, weekKey } from "../keys";
import { isTerminal, useEventStream, useServerEvents, type Operation } from "../events";
import { read } from "./request";
import { useWeek } from "./useWeek";
import type { components } from "../schema";

type PlanCurrency = components["schemas"]["PlanCurrency"];

/** How often the fallback asks, while the push connection is down and an operation is in flight. */
export const POLL_MS = 2000;

/** What a failed solve leaves to say, which is a notice rather than an error state. */
export interface OperationFailure {
  readonly operationId: string;
  /** The api's own sentence: what this status means and what still works. */
  readonly statement: string;
  readonly code: string | null;
  readonly message: string | null;
}

export interface UseOperationResult {
  /** The operation being tracked for this week, or null when none is. */
  readonly operation: Operation | null;
  readonly planCurrency: PlanCurrency;
  /** The failure to state at panel volume, or null. Cleared by the next operation. */
  readonly failure: OperationFailure | null;
  /**
   * Begin tracking an operation a mutation answered with.
   *
   * A pin, a solve, a tradeoff and an approval each answer with the operation they created or joined, and that
   * answer is a whole event earlier than any read. The caller has it, so the caller hands it over rather than this
   * hook re-reading the week to discover it.
   */
  readonly track: (operation: Operation) => void;
}

/** What is being followed: an identifier, and the last record seen for it, which a fresh chain hop has none of. */
interface Tracked {
  readonly id: string;
  readonly record: Operation | null;
}

export function useOperation(isoWeek: string): UseOperationResult {
  const week = useWeek(isoWeek);
  const { mutate } = useSWRConfig();
  const [tracked, setTracked] = useState<Tracked | null>(null);
  const [failure, setFailure] = useState<OperationFailure | null>(null);
  const { isConnected } = useEventStream();

  const seeded = week.status === "ready" ? week.data.operation : null;
  const current = tracked ?? (seeded === null ? null : { id: seeded.id, record: seeded });

  /* One reducer for all three arrivals -- the seed, a pushed event and a polled read -- so a status cannot be
   * handled one way when it is pushed and another when it is polled. */
  const settle = useCallback(
    (operation: Operation): void => {
      /* `supersededBy` is optional on the wire as well as nullable, so an absent successor and an explicit null
       * are one case: there is nothing to follow. */
      const successor = operation.supersededBy ?? null;
      if (operation.status === "superseded" && successor !== null) {
        setTracked({ id: successor, record: null });
        return;
      }
      setTracked({ id: operation.id, record: operation });
      if (operation.status === "succeeded") {
        setFailure(null);
        void mutate(weekKey(isoWeek));
      }
      if (operation.status === "failed") setFailure(failureOf(operation));
    },
    [isoWeek, mutate],
  );

  useServerEvents(
    useCallback(
      (event) => {
        if (event.type !== "operation") return;
        if (event.data.target.isoWeek !== isoWeek) return;
        settle(event.data);
      },
      [isoWeek, settle],
    ),
  );

  /* THE FALLBACK'S KEY IS NULL WHENEVER PUSH IS ANSWERING, which is what makes "reconnection returns to push" a
   * property of the key rather than of a teardown this module has to remember to run. */
  const isPending =
    current !== null && (current.record === null || !isTerminal(current.record.status));
  const pollKey = !isConnected && isPending && current !== null ? operationKey(current.id) : null;
  useSWR(pollKey, (key: string) => readOperation(idIn(key)), {
    refreshInterval: POLL_MS,
    onSuccess: settle,
  });

  const track = useCallback(
    (operation: Operation) => {
      setFailure(null);
      settle(operation);
    },
    [settle],
  );

  return {
    operation: current?.record ?? null,
    planCurrency: currencyOf(week.status === "ready" ? week.data.readings : null, current, failure),
    failure,
    track,
  };
}

/**
 * The word the strip renders, from the server's figure and the one thing this client knows first.
 *
 * The base is `readings.planCurrency`, so two surfaces cannot disagree. It is overridden only where this client
 * holds an operation state the read that produced those readings could not have seen: a non-terminal operation
 * created after it says `solving`, and a failure says `stale`.
 */
function currencyOf(
  readings: { readonly planCurrency: PlanCurrency } | null,
  tracked: Tracked | null,
  failure: OperationFailure | null,
): PlanCurrency {
  if (failure !== null) return "stale";
  if (tracked !== null && (tracked.record === null || !isTerminal(tracked.record.status))) {
    return "solving";
  }
  return readings?.planCurrency ?? "current";
}

function failureOf(operation: Operation): OperationFailure {
  return {
    operationId: operation.id,
    statement: operation.statement,
    code: operation.error?.code ?? null,
    message: operation.error?.message ?? null,
  };
}

async function readOperation(operationId: string): Promise<Operation> {
  return read(() =>
    client.GET("/api/v1/operations/{operation_id}", {
      params: { path: { operation_id: operationId } },
    }),
  );
}

/** The identifier inside an operation key, which is the request path the fallback will send. */
function idIn(key: string): string {
  return key.slice(key.lastIndexOf("/") + 1);
}
