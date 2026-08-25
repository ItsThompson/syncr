/* Asking the running stack what time it believes, and moving that belief.
 *
 * Moving goes through `just e2e-clock`, the recipe that owns writing the shift and restarting
 * the two processes that read it. Nothing here touches the variable or the containers directly:
 * one writer per surface, and the recipe is it.
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { COMPOSE_FILES, repoRoot } from "./compose.ts";

const run = promisify(execFile);

/** Which process to ask. These are exactly the services the overlay gives the offset to. */
export type StackService = "api" | "worker";

const INSTANT_PROBE = "from syncr_api.core.clock import utc_now; print(utc_now().isoformat())";

/** The instant `syncr_api.core.clock.utc_now` reports inside a RUNNING container, right now.
 *
 * An `exec` rather than a `run`: a one-shot would boot a fresh process whose environment was
 * resolved from the current files, and would answer for a stack the running containers had
 * never become. Only the live process can say what clock it is on.
 */
export const stackInstant = async (service: StackService): Promise<Date> => {
  const { stdout } = await run(
    "docker",
    ["compose", ...COMPOSE_FILES, "exec", "-T", service, "python", "-c", INSTANT_PROBE],
    { cwd: repoRoot },
  );
  const instant = new Date(stdout.trim());
  // An Invalid Date would poison every comparison downstream into a silent false, and the
  // caller would report a generic poll timeout instead of whatever the probe actually said.
  if (Number.isNaN(instant.getTime())) {
    throw new Error(`${service} did not report an instant: ${stdout.trim() || "(no output)"}`);
  }
  return instant;
};

/** Shift the stack's clock by `offset`, through the recipe that owns the shift.
 *
 * Blocks until api and worker have been recreated and report healthy again, so a caller that
 * gets past this await is talking to the shifted stack. Restore is `setStackClock("PT0S")`.
 */
export const setStackClock = async (offset: string): Promise<void> => {
  await run("just", ["e2e-clock", offset], { cwd: repoRoot });
};
