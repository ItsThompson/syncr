/* S17's other half: the capture flow an unfillable slot's gutter label opens.
 *
 * WHAT THIS FILE OWNS. `s01-materialization.spec.ts` asserts S17's reason half, that a solved week's slot whose
 * Area has no eligible content is drawn unfillable and names that Area. This file is the affordance behind that
 * rendering: activating the label opens capture prefilled with the slot's own Area and duration, and one confirm
 * produces a task that fits the slot, carrying a soft preference and no pin.
 *
 * WHY IT IS A BROWSER CASE AND NOT A COMPONENT ONE. The two defects a browser pass over this product's forms once
 * found were both invisible to a green unit suite: a select list drawn under a dialog's scrim, visible and
 * unclickable, and a form opening with the caret on its dismiss control so that typing typed nothing. A control a
 * pointer cannot reach and a prefill that reached a draft but not the rendered field are the same class, and jsdom
 * has neither layout nor hit-testing nor a computed style to see them with.
 *
 * THE FIRST CASE IS THAT CLASS, MEASURED. A band is transparent to the pointer, so a drag can begin on the canvas
 * underneath it, and the control inside the band inherited that: every gutter label the grid draws as a button read
 * `pointer-events: none`. The pair is asserted rather than the label alone, because a band that stopped refusing
 * the pointer would take the presses the canvas under it needs.
 *
 * THE SECOND CASE IS EXPECTED TO FAIL AT THIS COMMIT, and it is written as the assertion it will be rather than as
 * a skip, so the day the flow exists it goes red for passing unexpectedly and the marker has to be removed. Its
 * reason names every part that is missing, each measured rather than read.
 *
 * WHY THE PREFILL IS READ OFF THE RENDERED CONTROLS as well as from the task the confirm produces: see the
 * paragraph above about the two defects a browser found. The form is also asserted to open with nothing refused,
 * because a required field nobody has filled in yet is incomplete rather than wrong.
 *
 * THE URL IS DELIBERATELY NOT ASSERTED. The week screen states the opening in the query string, and the reader of
 * it clears the parameters once capture is open so a reload does not reopen the dialog. A case asserting the
 * parameters were still there afterwards would contradict that.
 *
 * WHICH SLOT IS DRIVEN, AND WHY IT IS DERIVED. The seed declares two slots a day and the solve decides which of
 * them it cannot fill, so naming one here would be a claim about a fixture rather than about the product. The case
 * takes the first day column holding exactly one empty slot and no labelled window, so the single activatable label
 * in that column is that slot's own, and it asserts that count rather than assuming it.
 *
 * WHAT THIS FILE DOES NOT BOUND: the label's wording. One wording per reason is `syncr_domain.gaps`'s statement,
 * and a copy of it here would be the second statement that rule exists to forbid.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Areas, EmptySlot, Preference, Tasks } from "../src/api/schemas.ts";
import { civilDateIn, dateIn, MONDAY, SUNDAY } from "../src/api/weeks.ts";
import { HOME_ZONE } from "../src/config.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { solveAndSettle, weekView } from "../src/harness/week.ts";

usingFixture("reference_week");

/* NOT serial, deliberately. Each case is self-sufficient about the state it needs, and one of the two is expected
 * to fail: in a serial file the first failure stops the rest, and a file whose purpose includes being shown to fail
 * has to be able to report on every case it reaches. `b1-s34-floors-and-unallocated.spec.ts` is the same shape for
 * the same reason. */

const MINUTE_MS = 60_000;
const MINUTES_IN_HOUR = 60;
const HOURS_IN_HALF_DAY = 12;

/** What the reader types, which is the one field a prefill cannot supply. */
const TITLE = "Ride the turbo trainer";

/* Every gutter label the grid drew, with the pointer policy computed for it and for the band holding it. A STRING
 * because the harness's tsconfig carries no DOM lib, which is why the readers in `s21-keyboard-and-focus.spec.ts`
 * are strings too. */
const LABELS_AND_THEIR_POINTER_POLICY = `[...document.querySelectorAll('.week-band__label')].map((label) => ({
  isControl: label.tagName.toLowerCase() === 'button',
  wording: label.textContent,
  onTheLabel: getComputedStyle(label).pointerEvents,
  onTheBand: label.parentElement === null ? 'no band' : getComputedStyle(label.parentElement).pointerEvents,
}))`;

interface PointerPolicy {
  readonly isControl: boolean;
  readonly wording: string;
  readonly onTheLabel: string;
  readonly onTheBand: string;
}

const minutesOf = (interval: EmptySlot["interval"]): number =>
  (Date.parse(interval.end) - Date.parse(interval.start)) / MINUTE_MS;

/** `HH:MM` on the wall clock of `zone`, which is the shape a preference window is stored in. */
const wallTimeIn = (instant: string, zone: string): string =>
  new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(instant));

/** Minutes from midnight for a stored wall time, which the api spells `HH:MM:SS`. */
const fromMidnight = (wallTime: string): number => {
  const [hours, minutes] = wallTime.split(":");
  return Number(hours) * MINUTES_IN_HOUR + Number(minutes);
};

test("S17 a gutter label drawn as a control takes the pointer, and the band holding it still refuses one", async ({
  api,
  page,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);

  await page.goto(`/week?week=${week}`);
  await page.waitForFunction("document.querySelectorAll('.week-band').length > 0");
  expect(page.url(), "the week screen redirected to sign-in").not.toContain("/sign-in");

  const drawn = (await page.evaluate(LABELS_AND_THEIR_POINTER_POLICY)) as PointerPolicy[];
  const controls = drawn.filter((each) => each.isControl);
  /* A LABEL THE PAYLOAD CARRIES IS DRAWN AS A CONTROL, and this week draws at least one: the stored label on the
   * interview's recovery window. Asserted, because a walk over an empty list measures nothing and would pass. */
  expect(
    controls.length,
    `the grid drew no gutter label as a control, so nothing was measured. It drew: ${JSON.stringify(drawn)}`,
  ).toBeGreaterThan(0);

  /* THE PAIR. A control inside the band opts back into the pointer; the band itself does not take one, so a press
   * on the hatch beside the words still reaches the canvas a drag begins on. */
  expect(controls.filter((each) => each.onTheLabel === "none")).toEqual([]);
  expect(controls.filter((each) => each.onTheBand !== "none")).toEqual([]);
});

test("S17 an unfillable slot's label opens capture prefilled, and one confirm produces a task that fits the slot", async ({
  api,
  page,
}) => {
  test.fail(
    true,
    "the flow behind the label does not exist yet, in three places and on one defect: an empty slot's band " +
      "carries no label to activate (ticket 1350); nothing reads the capture URL the week screen writes and " +
      "nothing writes a task's own preference (ticket 1490); and the grid's canvas is sized from the height of " +
      "the element that contains it, so it grows until layout stops and no pointer can act on it",
  );

  const week = planWeek();
  await solveAndSettle(api, week);
  const view = await weekView(api, week);
  const areas = await api.get<Areas>("/api/v1/areas");

  /* The columns as the grid draws them: seven local dates, Monday first. A band is drawn in the column its start's
   * LOCAL date falls in, so that is how a slot is assigned to one. */
  const dates = Array.from({ length: SUNDAY - MONDAY + 1 }, (_, step) =>
    dateIn(week, MONDAY + step),
  );
  const dateOf = (instant: string): string => civilDateIn(HOME_ZONE, new Date(instant));

  const columns = dates.map((date, column) => ({
    date,
    column,
    slots: view.live!.emptySlots.filter((slot) => dateOf(slot.interval.start) === date),
    labelled: view.live!.forbiddenWindows.filter(
      (window) => window.label !== null && dateOf(window.interval.start) === date,
    ).length,
  }));
  const unambiguous = columns.filter(
    (each) =>
      each.slots.length === 1 &&
      each.labelled === 0 &&
      each.slots[0]!.reason === "no_eligible_content",
  );
  expect(
    unambiguous.length,
    "no day column holds exactly one unfillable slot and no labelled window, so no column offers one " +
      `unambiguous invitation. The week drew: ${JSON.stringify(
        columns.map((each) => ({
          date: each.date,
          slots: each.slots.map((slot) => slot.reason),
          labelledWindows: each.labelled,
        })),
      )}`,
  ).toBeGreaterThan(0);

  const target = unambiguous[0]!;
  const slot = target.slots[0]!;
  const minutes = minutesOf(slot.interval);
  const areaName = areas.areas.find((area) => area.id === slot.areaId)?.name;
  expect(areaName, `the week names an Area the Areas read does not: ${slot.areaId}`).toBeDefined();

  const pinsBefore = view.pins.length;
  const backlogBefore = await api.get<Tasks>("/api/v1/tasks");

  await page.goto(`/week?week=${week}`);
  await page.waitForFunction("document.querySelectorAll('.week-block').length > 0");
  expect(page.url(), "the week screen redirected to sign-in").not.toContain("/sign-in");

  /* THE ONE INVITATION IN THAT COLUMN. An empty slot's label is a control and a window's is text, so the column
   * chosen above offers exactly one activatable label: the slot's own. */
  const invitation = page
    .locator(".week-day")
    .nth(target.column)
    .locator("button.week-band__label");
  await expect(
    invitation,
    `${target.date} holds one unfillable ${areaName ?? ""} slot of ${String(minutes)} minutes and no ` +
      "labelled window, so its column should offer exactly one activatable gutter label",
  ).toHaveCount(1);

  /* Every unsafe request the flow sends, recorded from before the label is activated: this criterion is as much
   * about a pin that must NOT be sent as about the two writes that must be. */
  const unsafe: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "GET") return;
    unsafe.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });

  await invitation.click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  /* THE PREFILL, AS THE READER SEES IT. The Area's control is a Radix trigger, so its rendered state is the option
   * text it shows; the estimate is a number field, so its rendered state is its value. */
  await expect(dialog.getByLabel("Area")).toHaveText(areaName!);
  await expect(dialog.getByLabel("Estimate")).toHaveValue(String(minutes));
  await expect(
    dialog.locator(".form-row__message--error"),
    "the form opened already complaining about a value the reader has not supplied",
  ).toHaveCount(0);

  await dialog.getByLabel("Task").fill(TITLE);
  await dialog.getByRole("button", { exact: true, name: "Capture" }).click();

  /* THE TASK, READ BACK OVER THE API rather than off the backlog table, because what the reader is promised is a
   * stored task that fits the slot they were looking at. */
  await expect
    .poll(async () => (await api.get<Tasks>("/api/v1/tasks")).tasks.map((task) => task.title))
    .toContain(TITLE);
  const backlogAfter = await api.get<Tasks>("/api/v1/tasks");
  const captured = backlogAfter.tasks.find((task) => task.title === TITLE)!;
  expect(captured.areaId).toBe(slot.areaId);
  expect(captured.estimateMinutes).toBe(minutes);
  expect(
    captured.minChunkMinutes,
    "the task's minimum chunk is longer than the slot, so it could never be placed in it",
  ).toBeLessThanOrEqual(minutes);
  expect(backlogAfter.tasks.length, "the one confirm produced more than one task").toBe(
    backlogBefore.tasks.length + 1,
  );

  /* THE SOFT PREFERENCE IS THE TASK'S OWN, not its Area's, and its window is the slot's own time of day: a
   * preference naming some other stretch of the day is not the one the reader asked for by activating that slot.
   * Containment rather than equality, because a widened window is still the slot's; bounded above, because a
   * window covering the whole day is not a preferred time at all. */
  const preference = await api.get<Preference>(`/api/v1/tasks/${captured.id}/preference`);
  expect(preference.declared, "the captured task declares no preference of its own").not.toBeNull();
  expect(preference.declared!.strength).toBe("soft");
  expect(preference.effective!.source.kind).toBe("task");
  expect(preference.declared!.windows.length).toBe(1);
  const preferred = preference.declared!.windows[0]!;
  expect(fromMidnight(preferred.start)).toBeLessThanOrEqual(
    fromMidnight(wallTimeIn(slot.interval.start, HOME_ZONE)),
  );
  expect(fromMidnight(preferred.end)).toBeGreaterThanOrEqual(
    fromMidnight(wallTimeIn(slot.interval.end, HOME_ZONE)),
  );
  expect(fromMidnight(preferred.end) - fromMidnight(preferred.start)).toBeLessThan(
    HOURS_IN_HALF_DAY * MINUTES_IN_HOUR,
  );

  /* AND NO PIN, from both ends: none was sent, and the week holds no more than it did. A capture states what the
   * work is, and pinning it would decide where it goes on the reader's behalf. */
  expect(unsafe.filter((each) => each.endsWith("/pins"))).toEqual([]);
  expect(unsafe.filter((each) => each === "POST /api/v1/tasks")).toHaveLength(1);
  expect(unsafe.filter((each) => /^PUT .*\/preference$/.test(each))).toHaveLength(1);
  const after = await weekView(api, week);
  expect(after.pins.length).toBe(pinsBefore);
});
