/* `partial_progress`: a task with a deadline and half its estimate already pinned, plus a past block
 * left unconfirmed.
 *
 * This is the fixture the probe's net-arithmetic properties are asked about, so both halves of the
 * netting have to be present at once: minutes that are PLACED and pinned, and minutes that are past
 * and unrecorded. The second half is not declared, it is what the clock leaves behind: every block in
 * this week before now has ended with no outcome recorded, which is what "unconfirmed" is.
 *
 * The pin is made here rather than by a scenario, because the fixture's name is what it is: the
 * progress is a precondition, not an observation. Making it needs a materialized and solved week, so
 * this fixture ticks the maintainer and solves before it pins, and the seeder's own trailing tick
 * then finds every week already planned and skips it.
 */

import type { ApiClient } from "../../api/client.ts";
import type { Block } from "../../api/schemas.ts";
import { dateIn, FRIDAY, utcMidnightOn } from "../../api/weeks.ts";
import { domainConstants, tickHorizon } from "../../harness/compose.ts";
import { planWeek } from "../../harness/subject-weeks.ts";
import { awaitLivePlan, solveAndSettle, weekView } from "../../harness/week.ts";
import { declareBaseline } from "../baseline.ts";
import { declareRoutine, declareSlot, declareTask } from "../declarations.ts";

export const seedPartialProgress = async (client: ApiClient): Promise<void> => {
  const stated = (await domainConstants()).partial_progress;
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
  // Two slots a day, so the week holds more than one placement of the task and half of it can be
  // pinned while the other half stays the solver's.
  await declareSlot(client, templateId, {
    areaId: areas.Career!,
    targetTime: "09:00:00",
    durationMinutes: 120,
  });
  await declareSlot(client, templateId, {
    areaId: areas.Career!,
    targetTime: "14:00:00",
    durationMinutes: 120,
  });

  const subject = planWeek();
  await declareTask(client, {
    title: stated.title,
    areaId: areas.Career!,
    estimateMinutes: stated.estimateMinutes,
    deadline: utcMidnightOn(dateIn(subject, FRIDAY)),
    minChunkMinutes: 60,
    priority: "high",
  });

  await tickHorizon();
  await awaitLivePlan(client, subject);
  await solveAndSettle(client, subject);

  const view = await weekView(client, subject);
  const placed = (view.live?.blocks ?? []).filter((block: Block) => block.title === stated.title);
  const half = placed.slice(0, Math.max(1, Math.floor(placed.length / 2)));
  for (const block of half) {
    await client.post(`/api/v1/weeks/${subject}/pins`, {
      blockId: block.id,
      start: block.interval.start,
    });
  }

  console.log(
    `partial_progress: ${stated.title} is ${stated.estimateMinutes} minutes due ` +
      `${dateIn(subject, FRIDAY)}; ${half.length} of its ${placed.length} placements are pinned`,
  );
};
