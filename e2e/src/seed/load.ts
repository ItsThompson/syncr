/* Loading a fixture: the four steps, in one place, for the CLI and for the suite both.
 *
 * A scenario seeds by calling this rather than by shelling out to the CLI, so a failure surfaces as
 * an exception with a stack rather than as a non-zero exit code and a captured stream. The CLI is a
 * thin wrapper over it, which is what keeps `just seed-reference` and a scenario's own `beforeAll`
 * from being two different procedures that drift.
 */

import { signIn, type ApiClient } from "../api/client.ts";
import { BASE_URL, E2E_EMAIL, E2E_PASSWORD } from "../config.ts";
import { bootstrapAccount, materializeWeeks, resetDatabase, tickHorizon } from "../harness/compose.ts";
import { currentWeek, planWeek } from "../harness/subject-weeks.ts";
import { awaitLivePlan } from "../harness/week.ts";
import { FIXTURES, fixtureNames } from "./fixtures.ts";

export type Loaded = {
  readonly client: ApiClient;
  readonly log: readonly string[];
};

export type FixturePlanState = "materialized" | "solved";

/** Empty the database, provision the tenant, declare `name`, and establish the requested plan state. */
export const loadFixture = async (
  name: string,
  planState: FixturePlanState = "solved",
): Promise<Loaded> => {
  const seed = FIXTURES[name];
  if (!seed)
    throw new Error(`${name} is not a fixture. The fixtures are: ${fixtureNames().join(", ")}`);

  const log: string[] = [];
  log.push((await resetDatabase()).trim());
  log.push((await bootstrapAccount()).trim());

  const client = await signIn(BASE_URL, E2E_EMAIL, E2E_PASSWORD);
  await seed(client);
  log.push(`declared ${name} over ${BASE_URL}`);

  const horizonWeeks = [currentWeek(), planWeek()];
  if (planState === "materialized") {
    await materializeWeeks(horizonWeeks);
    log.push("materialized the horizon plans without solving");
  } else {
    await tickHorizon();
    await Promise.all(horizonWeeks.map((isoWeek) => awaitLivePlan(client, isoWeek)));
    log.push("settled the horizon plans");
  }
  return { client, log };
};
