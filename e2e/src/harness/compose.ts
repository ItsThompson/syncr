/* The three one-shots the harness runs inside the stack, and the compose invocation they share.
 *
 * Two of them exist because they cannot be done over HTTP. There is no route that creates an
 * account, because the product has no sign-up, and there is no route that empties a database. The
 * third is the plan-horizon maintainer's tick, which S1 names as "wait for the next tick, or trigger
 * it": the wait is fifteen minutes because the runner's first tick only sets its own due time, so the
 * suite triggers it.
 *
 * Each runs the REAL instrument. `syncr-bootstrap-user` is the console script a first deployment
 * runs, and the tick drives `PlanHorizonRunner` through the worker's own iteration. Neither is a
 * shortcut past the code under test; both are that code, invoked where a person would invoke it.
 */

import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

import { E2E_EMAIL, E2E_PASSWORD } from "../config.ts";

const run = promisify(execFile);

/* The repository root, from this file's own location, so a recipe may be run from anywhere. */
export const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..");

/* Both files, in this order, so the project directory is the repository root and every relative
 * path in the overlay resolves from there. This is the same pair `just e2e-up` passes. */
export const COMPOSE_FILES = [
  "-f",
  "docker-compose.yml",
  "-f",
  "e2e/docker-compose.e2e.yml",
] as const;

/* A one-shot must not start dependencies: Postgres is already up, and `run` without this waits on
 * a health check it does not need. */
const ONE_SHOT = ["run", "--rm", "--no-deps"] as const;

const compose = async (
  args: readonly string[],
  env: Readonly<Record<string, string>> = {},
): Promise<string> => {
  try {
    const { stdout } = await run("docker", ["compose", ...COMPOSE_FILES, ...args], {
      cwd: repoRoot,
      env: { ...process.env, ...env },
    });
    return stdout;
  } catch (failure) {
    const stderr = (failure as { stderr?: string }).stderr ?? "";
    throw new Error(
      `docker compose ${args.join(" ")} failed. Is the e2e stack up? Run \`just e2e-up\`.\n${stderr}`,
    );
  }
};

/** Empty every domain table. The schema and the migration marker are left alone. */
export const resetDatabase = async (): Promise<string> =>
  compose([...ONE_SHOT, "worker", "python", "/harness/reset.py"]);

/** Provision the tenant and its user through the console script a first deployment runs. */
export const bootstrapAccount = async (): Promise<string> =>
  compose([
    ...ONE_SHOT,
    "-e",
    `SYNCR_BOOTSTRAP_EMAIL=${E2E_EMAIL}`,
    "-e",
    `SYNCR_BOOTSTRAP_PASSWORD=${E2E_PASSWORD}`,
    "api",
    "syncr-bootstrap-user",
  ]);

/** Tick the plan-horizon maintainer once, over every tenant, now. */
export const tickHorizon = async (): Promise<string> =>
  compose([...ONE_SHOT, "worker", "python", "/harness/tick.py"]);

export type DomainConstants = {
  readonly elastic_sleep: {
    readonly title: string;
    readonly targetTime: string;
    readonly durationMinutes: number;
    readonly minDurationMinutes: number;
    readonly giveMinutes: number;
    readonly gapMinutes: number;
    readonly reductionEach: number;
  };
  readonly partial_progress: {
    readonly title: string;
    readonly estimateMinutes: number;
    readonly remainingMinutes: number;
    readonly careerFloorMinutes: number;
    readonly fitnessFloorMinutes: number;
  };
  readonly recovery_scopes: { readonly label: string; readonly recoveryMinutes: number };
  readonly dst_weeks: {
    readonly zone: string;
    readonly sleepTargetTime: string;
    readonly sleepDurationMinutes: number;
  };
};

let cached: DomainConstants | null = null;

/** The numbers `syncr_domain.fixtures` states, read from the package rather than restated here.
 *
 * Cached for the process: it is one container run, and five fixtures ask for it. */
export const domainConstants = async (): Promise<DomainConstants> => {
  cached ??= JSON.parse(
    await compose([...ONE_SHOT, "worker", "python", "/harness/constants.py"]),
  ) as DomainConstants;
  return cached;
};

export type VerdictEventRow = {
  readonly isoWeek: string;
  readonly occurredAt: string;
  readonly feasible: boolean;
  readonly provenance: string;
  readonly surface: string;
  readonly sessionModeActive: boolean;
  readonly shortfallKinds: readonly string[];
  readonly inputVersion: number;
};

export type VerdictEvents = {
  readonly rows: readonly VerdictEventRow[];
  readonly caughtEarlyByTenant: Readonly<Record<string, number | null>>;
};

/** Every recorded verdict transition, and the early-catch ratio the product's own rule reads. */
export const verdictEvents = async (): Promise<VerdictEvents> =>
  JSON.parse(
    await compose([...ONE_SHOT, "worker", "python", "/harness/verdict_events.py"]),
  ) as VerdictEvents;
