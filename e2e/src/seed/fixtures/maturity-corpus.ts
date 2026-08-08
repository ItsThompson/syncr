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
 * IT TOLERATES ONE NAMED REFUSAL RATHER THAN EXITING ON IT. A solve of a week whose earlier days are
 * already past is refused with `past_disagreement`, permanently, because the plan-horizon maintainer
 * materializes a live plan and that closes the escape hatch `plans/settled.py` leaves for a week with
 * no live plan. That is ticket 1570, a defect in the product rather than in this seed: until it lands,
 * the current week's blocks are the ones the maintainer placed, which is a smaller corpus and a real
 * one. So the refusal is named, printed, and continued past. Any OTHER failure still stops the seed.
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

/* The refusal ticket 1570 owns. Named as a value, so tolerating it is a decision about ONE known state
 * rather than a blanket "any failure is acceptable". */
const KNOWN_REFUSAL = "past_disagreement";

/** Solve `isoWeek` and say what happened, tolerating only the refusal ticket 1570 owns.
 *
 * It waits for the refusal to APPEAR rather than for the operation to reach a terminal status: the queue
 * retries three times with a doubling backoff, so a permanently refused solve takes minutes to report
 * `failed` while its answer is already on the row after the first attempt. */
const solveTolerating1570 = async (
  client: ApiClient,
  isoWeek: string,
): Promise<"solved" | "refused"> => {
  const started = await solveNow(client, isoWeek);
  const answered = await until(
    `${isoWeek}'s solve to succeed or to state a reason`,
    () => operation(client, started.id),
    (seen) => seen.status === "succeeded" || seen.error !== null,
    45_000,
  );
  if (answered.status === "succeeded") return "solved";
  if (answered.error?.code === KNOWN_REFUSAL) return "refused";
  throw new Error(
    `solving ${isoWeek} ended ${answered.status}: ${answered.statement} ` +
      JSON.stringify(answered.error),
  );
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
  const refused: string[] = [];
  const refusedRecordings: string[] = [];
  let recorded = 0;
  for (const isoWeek of weeks) {
    const view: WeekView = await weekView(client, isoWeek);
    if (view.live === null) {
      refused.push(`${isoWeek} holds no plan`);
      continue;
    }
    const outcome = await solveTolerating1570(client, isoWeek);
    (outcome === "solved" ? solved : refused).push(isoWeek);
    // Read again whatever happened: a refused solve leaves the materialized plan, whose blocks are a
    // smaller corpus and a real one.
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
  if (refused.length > 0) {
    console.log(
      `maturity_corpus: NOT solved: ${refused.join(", ")}. A week whose earlier days are already ` +
        `past is refused with ${KNOWN_REFUSAL}, permanently, which is ticket 1570. Its materialized ` +
        "blocks are still recorded against.",
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
