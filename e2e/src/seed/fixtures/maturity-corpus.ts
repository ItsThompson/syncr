/* `maturity_corpus`: outcomes and edit events sized to sit either side of each gate.
 *
 * WHERE THE SIZES ARE READ, AND WHAT IS VISIBLE WITHOUT A FIT. `GET /api/v1/learned` reports, per
 * parameter, how many observations are behind it and how many it needs, so this fixture records outcomes
 * and then asks the app rather than holding a number: a fixture spelling "eleven" would stop straddling
 * a gate the day the gate moved. On a tenant whose weight set has never been fitted the parameter list
 * is EMPTY, because the rows describe a fit, so what the print reports is the corpus it built and the
 * fact that the per-parameter counts appear only once the nightly fitter has run. This stack does not
 * run it: the learning image is a scheduled one-shot outside the e2e overlay, and `just learn-once` is
 * the step that produces the fit those rows describe.
 *
 * WHAT BOUNDS IT, AND WHY THAT IS HONEST. An outcome can only be recorded against a block that has
 * ended, and the only weeks holding blocks are the ones inside the horizon, so the corpus this
 * fixture can build is bounded by how far into the current week today is. It records every block it
 * can and prints what it reached; it does not manufacture a past. A gate needing thirty confirmed
 * observations of one binding is therefore reachable on a Friday and not on a Monday, and the print
 * says which.
 *
 * EVERY WEEK SOLVES, AND ANY FAILURE STOPS THE SEED. The binding phase leaves a slot the week has
 * already reached unbound, so a first solve of a partly lived week succeeds rather than drawing
 * `past_disagreement`. The seed no longer tolerates that refusal: a solve that fails for any reason
 * stops the seed, because the tolerance was the record of the defect and the defect is closed.
 */

import type { ApiClient } from "../../api/client.ts";
import type { Block, WeekView } from "../../api/schemas.ts";
import { isoWeekShift } from "../../api/weeks.ts";
import { tickHorizon } from "../../harness/compose.ts";
import { currentWeek } from "../../harness/subject-weeks.ts";
import { operation, solveNow, until, weekView } from "../../harness/week.ts";
import { declareBaseline } from "../baseline.ts";
import { declareHabit, declareRoutine, declareSlot, declareTask } from "../declarations.ts";

type Learned = {
  readonly version: number;
  readonly origin: string;
  readonly collecting: number;
  readonly ready: number;
  readonly parameters: readonly {
    readonly parameter: string;
    readonly samples: number;
    readonly threshold: number;
    readonly state: string;
  }[];
};

/* Three weeks, which is what a 14-day horizon covers when today is mid-week. Every one of them is
 * read, and only blocks that have ended are recorded against. */
const WEEKS_AHEAD = 2;

const hasEnded = (block: Block, now: Date): boolean => new Date(block.interval.end) < now;

/** Solve `isoWeek` and refuse anything but success, so a failure stops the seed.
 *
 * It waits for the operation to reach a terminal status: the queue retries three times with a
 * doubling backoff, so a permanently refused solve takes minutes to report `failed`. */
const solveWeek = async (client: ApiClient, isoWeek: string): Promise<void> => {
  const started = await solveNow(client, isoWeek);
  const settled = await until(
    `${isoWeek}'s solve to reach a terminal status`,
    () => operation(client, started.id),
    (seen) =>
      seen.status === "succeeded" || seen.status === "failed" || seen.status === "superseded",
    45_000,
  );
  if (settled.status !== "succeeded") {
    throw new Error(
      `solving ${isoWeek} ended ${settled.status}: ${settled.statement} ` +
        JSON.stringify(settled.error),
    );
  }
};

export const seedMaturityCorpus = async (client: ApiClient): Promise<void> => {
  const { areas, templateId } = await declareBaseline(client);

  await declareRoutine(client, templateId, {
    title: "Sleep",
    targetTime: "23:00:00",
    durationMinutes: 480,
  });
  await declareRoutine(client, templateId, {
    title: "Wake Up",
    targetTime: "07:00:00",
    durationMinutes: 15,
  });
  await declareRoutine(client, templateId, {
    title: "Shower",
    targetTime: "07:15:00",
    durationMinutes: 15,
  });
  await declareRoutine(client, templateId, {
    title: "Dinner",
    targetTime: "19:00:00",
    durationMinutes: 60,
  });
  // A habit on every day, so one binding accumulates the most observations of anything in the week:
  // the per-binding gates are the ones a whole-week corpus reaches first.
  await declareHabit(client, {
    title: "Gym",
    areaId: areas.Fitness!,
    minDurationMinutes: 45,
    timesPerWeek: 7,
    bindingSource: "fixed",
  });
  await declareSlot(client, templateId, {
    areaId: areas.Career!,
    targetTime: "09:00:00",
    durationMinutes: 90,
  });
  await declareTask(client, {
    title: "Career reading",
    areaId: areas.Career!,
    estimateMinutes: 600,
    minChunkMinutes: 30,
  });

  await tickHorizon();

  const thisWeek = currentWeek();
  const weeks = [
    thisWeek,
    ...Array.from({ length: WEEKS_AHEAD }, (_, n) => isoWeekShift(thisWeek, n + 1)),
  ];

  const now = new Date();
  const solved: string[] = [];
  const unplanned: string[] = [];
  const refusedRecordings: string[] = [];
  let recorded = 0;
  for (const isoWeek of weeks) {
    const view: WeekView = await weekView(client, isoWeek);
    if (view.live === null) {
      // OUTSIDE THE HORIZON, which is what happens to the third week early in a week: `today + 14 days`
      // stops short of it. Kept in its own list for that reason, because it is a different state from a
      // solved week: the maintainer has not reached it and there is nothing to record against.
      unplanned.push(isoWeek);
      continue;
    }
    await solveWeek(client, isoWeek);
    solved.push(isoWeek);
    // Read again after the solve: the solved plan's blocks are the corpus to record against.
    const current = await weekView(client, isoWeek);
    for (const block of current.live?.blocks ?? []) {
      if (!hasEnded(block, now)) continue;
      // Alternating states, so the corpus carries both a completion and a skip for the same binding:
      // a skip-probability fit over nothing but completions has no variance to fit.
      const state = recorded % 4 === 3 ? "skipped" : "completed";
      const reply = await client.attempt<{ detail?: string }>(
        "PUT",
        `/api/v1/blocks/${block.id}/outcome`,
        { isoWeek, state, actualInterval: null, actualMinutes: null },
      );
      if (reply.status === 200) {
        recorded += 1;
      } else {
        // Printed rather than dropped: a corpus smaller than the log implies, with no reason given, is
        // the shape that makes a later learning question unanswerable.
        refusedRecordings.push(`${block.title} ${reply.status} ${reply.body?.detail ?? ""}`.trim());
      }
    }
  }

  const learned = await client.get<Learned>("/api/v1/learned");
  console.log(`maturity_corpus: recorded ${recorded} outcomes`);
  console.log(`maturity_corpus: solved ${solved.join(", ") || "no week"}`);
  if (unplanned.length > 0) {
    console.log(
      `maturity_corpus: NOT planned: ${unplanned.join(", ")}. Outside the horizon, so the maintainer ` +
        "has not reached it and there is nothing to record against. Not the same state as a solved " +
        "week.",
    );
  }
  if (refusedRecordings.length > 0) {
    console.log(`maturity_corpus: ${refusedRecordings.length} recordings were refused:`);
    for (const refusal of refusedRecordings) console.log(`maturity_corpus:   ${refusal}`);
  }
  if (learned.parameters.length === 0) {
    console.log(
      `maturity_corpus: weight set ${learned.version} is ${learned.origin} and has never been ` +
        "fitted, so it reports no per-parameter counts. Run the nightly fitter to see which of these " +
        "observations crossed a gate; this stack does not run it.",
    );
    return;
  }
  console.log(`maturity_corpus: ${learned.ready} ready, ${learned.collecting} collecting`);
  for (const row of learned.parameters) {
    console.log(`maturity_corpus:   ${row.parameter} ${row.samples}/${row.threshold} ${row.state}`);
  }
};
