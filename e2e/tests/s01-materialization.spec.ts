/* S1: a week materializes, automatically.
 *
 * The precondition is the seed's: Areas, one day shape, and a week pattern declared, and the
 * plan-horizon maintainer triggered rather than waited fifteen minutes for.
 *
 * S1's second half is the one worth having, and it is the half a unit test cannot reach: a week fifty
 * weeks out has to state its own emptiness AND TRIGGER NO SOLVE. Reading a week is the one path in
 * this product where an accidental write would look like a feature, so the assertion is over the
 * operation list before and after the read rather than over the response alone.
 */

import { test, expect, usingFixture } from "./harness.ts";
import { beyondHorizonWeek, currentWeek, planWeek } from "../src/harness/subject-weeks.ts";
import { operationsFor, solveAndSettle, weekView } from "../src/harness/week.ts";

usingFixture("reference_week");
test.describe.configure({ mode: "serial" });

test("S1 every week inside the horizon acquires a plan without being asked", async ({ api }) => {
  for (const isoWeek of [currentWeek(), planWeek()]) {
    const view = await weekView(api, isoWeek);
    expect(view.live, `${isoWeek} holds no plan`).not.toBeNull();
    expect(view.emptyWeek).toBeNull();
    expect(view.live!.blocks.length).toBeGreaterThan(0);
  }

  const revisions = await api.get<{ revisions: readonly { reason: string }[] }>(
    `/api/v1/weeks/${planWeek()}/revisions`,
  );
  const reasons = revisions.revisions.map((revision) => revision.reason);
  expect(reasons.some((reason) => reason === "materialized" || reason === "horizon_advanced")).toBe(
    true,
  );
});

test("S1 the frame is drawn with no Area pigment and a fifteen-minute block still has a title", async ({
  api,
}) => {
  const view = await weekView(api, planWeek());
  const frame = view.live!.blocks.filter((block) => block.origin === "frame");
  expect(frame.length).toBeGreaterThan(0);
  for (const block of frame) expect(block.areaId).toBeNull();

  const compact = frame.filter((block) => block.title === "Wake Up");
  expect(compact.length).toBe(7);
  for (const block of compact) {
    const minutes = (Date.parse(block.interval.end) - Date.parse(block.interval.start)) / 60_000;
    expect(minutes).toBe(15);
    expect(block.title).toBe("Wake Up");
  }
});

test("S1 and S24 every Area slot is present, drawn as not solved because nobody looked at the backlog", async ({
  api,
}) => {
  const view = await weekView(api, planWeek());
  expect(view.live!.emptySlots.length).toBeGreaterThan(0);
  for (const slot of view.live!.emptySlots) {
    // `not_solved` and NOT `no_eligible_content`, which are two different states: this is the rendering
    // for a slot nobody has looked at the backlog for, and the other one is for a slot whose backlog
    // was looked at and was empty. S17 is the scenario that observes the second.
    expect(slot.reason).toBe("not_solved");
    expect(slot.areaId).not.toBeNull();
  }
});

test("S17 a slot whose Area has content that cannot take its duration is drawn as unfillable, naming that Area", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);
  const view = await weekView(api, week);

  // The solve looked at the backlog, so a slot it could not fill carries the reason that says so. The
  // reference week declares a Fitness slot of sixty minutes and a Gym habit of forty-five, so the
  // Area holds content but none of it can take the slot's duration, which is the case S17 opens with.
  const unfillable = view.live!.emptySlots.filter((slot) => slot.reason === "no_fitting_content");
  expect(
    unfillable.length,
    `no slot was drawn unfillable; the reasons present were ` +
      `${[...new Set(view.live!.emptySlots.map((slot) => slot.reason))].join(", ")}`,
  ).toBeGreaterThan(0);

  // It stays at its declared time and duration, and it names the Area whose content is missing, which is
  // what the label reads and what capture would be prefilled from.
  const areas = await api.get<{ areas: readonly { id: string; name: string }[] }>("/api/v1/areas");
  const named = new Set(areas.areas.map((area) => area.id));
  for (const slot of unfillable) {
    expect(named.has(slot.areaId)).toBe(true);
    expect(Date.parse(slot.interval.end)).toBeGreaterThan(Date.parse(slot.interval.start));
  }
});

test("S1 a week fifty weeks out states the horizon and triggers no solve", async ({ api }) => {
  const far = beyondHorizonWeek();
  const before = await operationsFor(api, far);

  const view = await weekView(api, far);
  expect(view.live).toBeNull();
  expect(view.emptyWeek).not.toBeNull();
  expect(view.emptyReason).toBe("outside_horizon");
  // The statement names the horizon, in days and as a date, because a user who cannot see this week
  // needs to know what would bring it in.
  expect(view.emptyWeek!.statement).toContain(`${view.emptyWeek!.horizonDays}-day`);
  expect(view.emptyWeek!.statement).toContain(view.emptyWeek!.horizonThrough);
  expect(view.emptyWeek!.coversThisWeek).toBe(false);

  // Two actions, and the statement is what offers them: extend the horizon, or solve this week now.
  expect(view.emptyWeek!.statement).toMatch(/[Ee]xtend the horizon/);
  expect(view.emptyWeek!.statement).toMatch(/solve this week now/);

  // The read wrote nothing. A second read, to catch a write that only the first read would make.
  await weekView(api, far);
  const after = await operationsFor(api, far);
  expect(after.length).toBe(before.length);
  expect(view.operation).toBeNull();
});
