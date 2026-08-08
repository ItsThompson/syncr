/* `maturity_corpus`: outcomes and edit events sized to sit either side of each gate.
 *
 * THE SIZES ARE DERIVED FROM THE APP, NOT WRITTEN DOWN HERE. `GET /api/v1/learned` reports, per
 * parameter, how many observations are behind it and how many it needs, so this fixture records
 * outcomes and then reads which parameters the tenant has crossed and which it has not. A fixture
 * holding "eleven" would silently stop straddling a gate the day the gate moved, which is the reason
 * the learning package's own corpus computes its sizes from the thresholds rather than naming them.
 *
 * WHAT BOUNDS IT, AND WHY THAT IS HONEST. An outcome can only be recorded against a block that has
 * ended, and the only weeks holding blocks are the ones inside the horizon, so the corpus this
 * fixture can build is bounded by how far into the current week today is. It records every block it
 * can and prints what it reached; it does not manufacture a past. A gate needing thirty confirmed
 * observations of one binding is therefore reachable on a Friday and not on a Monday, and the print
 * says which.
 */

import type { ApiClient } from "../../api/client.ts";
import type { Block, WeekView } from "../../api/schemas.ts";
import { civilDateIn, isoWeekOf, isoWeekShift } from "../../api/weeks.ts";
import { HOME_ZONE } from "../../config.ts";
import { tickHorizon } from "../../harness/compose.ts";
import { awaitLivePlan, solveAndSettle, weekView } from "../../harness/week.ts";
import { declareBaseline } from "../baseline.ts";
import { declareHabit, declareRoutine, declareSlot, declareTask } from "../declarations.ts";

type Learned = {
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

  const thisWeek = isoWeekOf(civilDateIn(HOME_ZONE));
  const weeks = [thisWeek, ...Array.from({ length: WEEKS_AHEAD }, (_, n) => isoWeekShift(thisWeek, n + 1))];

  const now = new Date();
  let recorded = 0;
  for (const isoWeek of weeks) {
    const view: WeekView = await client
      .get<WeekView>(`/api/v1/weeks/${isoWeek}`)
      .catch(() => ({ live: null }) as WeekView);
    if (view.live === null) continue;
    await awaitLivePlan(client, isoWeek);
    await solveAndSettle(client, isoWeek);
    const solved = await weekView(client, isoWeek);
    for (const block of solved.live?.blocks ?? []) {
      if (!hasEnded(block, now)) continue;
      // Alternating states, so the corpus carries both a completion and a skip for the same binding:
      // a skip-probability fit over nothing but completions has no variance to fit.
      const state = recorded % 4 === 3 ? "skipped" : "completed";
      const reply = await client.attempt("PUT", `/api/v1/blocks/${block.id}/outcome`, {
        isoWeek,
        state,
        actualInterval: null,
        actualMinutes: null,
      });
      if (reply.status === 200) recorded += 1;
    }
  }

  const learned = await client.get<Learned>("/api/v1/learned");
  const straddling = learned.parameters.map(
    (row) => `${row.parameter} ${row.samples}/${row.threshold} ${row.state}`,
  );
  console.log(`maturity_corpus: recorded ${recorded} outcomes`);
  console.log(`maturity_corpus: ${learned.ready} ready, ${learned.collecting} collecting`);
  for (const row of straddling) console.log(`maturity_corpus:   ${row}`);
};
