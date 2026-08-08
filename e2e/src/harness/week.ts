/* Reading a week, driving a solve, and waiting for the worker: what every scenario shares.
 *
 * WHY THE WAITS ARE POLLS RATHER THAN SLEEPS. The worker ticks on its own five-second cadence and a
 * debounced solve becomes due 1.5 seconds after the mutation that scheduled it, so the moment a
 * result appears is a function of two clocks the suite does not own. A fixed sleep either wastes
 * that time on every scenario or fails intermittently; a poll on the state the scenario is actually
 * about fails only when the state never arrives, and says which state that was.
 *
 * Nothing here shortens a debounce, freezes a clock, or bypasses the queue. The one thing it does
 * use is `?immediate=true` on the solve route, which is a documented parameter of the product and
 * not a test hook: it is what the CLI's `--wait` and the session's own solves pass.
 */

import { stated, type ApiClient } from "../api/client.ts";
import type { Operation, PendingProposal, WeekView } from "../api/schemas.ts";
import { WORKER_GRACE_MS } from "../config.ts";

const POLL_INTERVAL_MS = 250;

const TERMINAL: readonly string[] = ["succeeded", "failed", "superseded"];

const pause = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** Poll `read` until `holds` answers true, or say what was last seen when the wait runs out. */
export const until = async <T>(
  what: string,
  read: () => Promise<T>,
  holds: (seen: T) => boolean,
  timeoutMs: number = WORKER_GRACE_MS,
): Promise<T> => {
  const deadline = Date.now() + timeoutMs;
  let seen = await read();
  while (!holds(seen)) {
    if (Date.now() > deadline) {
      throw new Error(
        `waited ${timeoutMs}ms for ${what} and it never held. Last read: ${JSON.stringify(seen)}`,
      );
    }
    await pause(POLL_INTERVAL_MS);
    seen = await read();
  }
  return seen;
};

export const weekView = (client: ApiClient, isoWeek: string): Promise<WeekView> =>
  client.get<WeekView>(`/api/v1/weeks/${isoWeek}`);

/** Ask for a solve now rather than after the debounce, and answer with the operation it created. */
export const solveNow = (client: ApiClient, isoWeek: string): Promise<Operation> =>
  client.post<Operation>(`/api/v1/weeks/${isoWeek}/solve?immediate=true`);

/** Ask for a debounced solve, which is what a mutation schedules. */
export const solveDebounced = (client: ApiClient, isoWeek: string): Promise<Operation> =>
  client.post<Operation>(`/api/v1/weeks/${isoWeek}/solve`);

/** One operation by identifier.
 *
 * A 404 HERE IS REPORTED AS THE KNOWN DEFECT IT PROBABLY IS, AND IT IS STILL A FAILURE. A route that
 * answers an operation identifier can answer one this read then 404s for, from more than one route, which
 * is ticket 1575. The reason this wrapper exists is legibility rather than tolerance: `awaitTerminal` is on
 * the hot path of almost every scenario, so without a message naming the defect the same phantom identifier
 * reads like a product bug in whichever case happens to draw it.
 *
 * NO RATE IS PRINTED HERE. Every measurement of it has come out different and each new sample has been worse
 * than the last, from one in twenty-five to one in five; a figure in a message is the one number a future
 * reader trusts, and it cannot be kept current in source. Ticket 1575 carries the samples, and
 * `docs/smoke-scenarios.md` cites the planning figure.
 *
 * It deliberately does NOT retry. A read that answers 404 for an identifier the api has just handed out is
 * a product defect, and a silent retry would convert it into a slow test instead of a red one. */
export const operation = async (client: ApiClient, id: string): Promise<Operation> => {
  const reply = await client.attempt<Operation>("GET", `/api/v1/operations/${id}`);
  if (reply.status === 404) {
    throw new Error(
      `operation ${id} answered 404, and it is the identifier the api had just returned. That is the ` +
        "phantom-operation defect in ticket 1575, which names its measured rate; it is not a fault in " +
        "this scenario. Re-run it, and add the run to that ticket's evidence.",
    );
  }
  if (reply.status !== 200) {
    throw new Error(stated("GET", `/api/v1/operations/${id}`, reply));
  }
  return reply.body;
};

/** Wait until the worker has finished with `id`, whichever way it finished. */
export const awaitTerminal = (
  client: ApiClient,
  id: string,
  timeoutMs?: number,
): Promise<Operation> =>
  until(
    `operation ${id} to reach a terminal status`,
    () => operation(client, id),
    (seen) => TERMINAL.includes(seen.status),
    timeoutMs,
  );

/** Solve, wait, and refuse anything but success, so a scenario's setup cannot pass on a failure. */
export const solveAndSettle = async (client: ApiClient, isoWeek: string): Promise<Operation> => {
  const started = await solveNow(client, isoWeek);
  const settled = await awaitTerminal(client, started.id);
  if (settled.status !== "succeeded") {
    throw new Error(
      `solving ${isoWeek} ended ${settled.status}: ${settled.statement} ${JSON.stringify(settled.error)}`,
    );
  }
  return settled;
};

/** Wait until the week holds a live plan, which is what a materialization or an adoption leaves. */
export const awaitLivePlan = (client: ApiClient, isoWeek: string): Promise<WeekView> =>
  until(
    `${isoWeek} to hold a live plan`,
    () => weekView(client, isoWeek),
    (seen) => seen.live !== null,
  );

/** Wait until the pending slot holds a proposal, which is what a diff with a move leaves.
 *
 * The route answers 404 while the slot is empty rather than a null body, so the wait reads the
 * status rather than the payload. */
export const awaitProposal = async (
  client: ApiClient,
  isoWeek: string,
): Promise<PendingProposal> => {
  const reply = await until(
    `${isoWeek} to hold a pending proposal`,
    () => client.attempt<PendingProposal>("GET", `/api/v1/weeks/${isoWeek}/proposal`),
    (seen) => seen.status === 200,
  );
  return reply.body;
};

/** The pending proposal if the slot holds one, and null while it is empty. */
export const pendingProposal = async (
  client: ApiClient,
  isoWeek: string,
): Promise<PendingProposal | null> => {
  const reply = await client.attempt<PendingProposal>("GET", `/api/v1/weeks/${isoWeek}/proposal`);
  if (reply.status === 404) return null;
  if (reply.status !== 200) {
    throw new Error(`reading ${isoWeek}'s proposal answered ${reply.status}`);
  }
  return reply.body;
};

/** Every operation recorded for a week, newest first, which is what a burst is counted from. */
export const operationsFor = async (
  client: ApiClient,
  isoWeek: string,
): Promise<readonly Operation[]> => {
  const answered = await client.get<{ operations: readonly Operation[] }>("/api/v1/operations");
  return answered.operations.filter((each) => each.target.isoWeek === isoWeek);
};
