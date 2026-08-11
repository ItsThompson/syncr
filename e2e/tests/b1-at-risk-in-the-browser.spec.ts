/* THE AT-RISK ROW TREATMENT, DRIVEN THROUGH THE RENDERED SCREEN.
 *
 * WHAT THIS FILE OWNS, AND WHAT IT DELIBERATELY LEAVES ALONE. `b1-s34-floors-and-unallocated.spec.ts` crosses the
 * backlog's at-risk column against the current week's verdict over the api, in both directions, and that is the
 * stronger guard on the DETERMINATION: it is untouched. What no case in this suite has ever done is load
 * `/backlog` in a browser, so the other half of the seam has been unbounded. A determination nothing renders and
 * a rendering of nothing are indistinguishable from the api.
 *
 * THREE RENDERINGS OF ONE FIELD, WHICH IS WHY THE BROWSER IS THE INSTRUMENT. `atRisk` arrives on the row, and the
 * screen spends it three times: the row carries `data-at-risk`, the reserved mark cell says the standing in words
 * for a reader who cannot see the mark, and the band states a count. A component suite can render each of the
 * three from a fixture it wrote itself; what it cannot see is whether the screen asks the api for that field at
 * all, and whether the three agree once a real read has landed.
 *
 * THE STANDING FILTER IS COMPONENT STATE RATHER THAN A QUERY PARAMETER, so this case drives the control. Nothing
 * in the address bar states which standing is selected: `useBacklogScreen` holds it, and what reaches the api is
 * the request the select's change makes. A case that navigated to a URL carrying the narrowing would assert a
 * screen this product does not have.
 *
 * AND THE NARROWING IS THE SERVER'S, WHICH THIS FILE RECORDS RATHER THAN ASSUMES. At risk is the week verdict's
 * determination and not a comparison a client can make, so the request the select sends is asserted alongside the
 * rows it comes back with: a screen that filtered a list it was already holding would satisfy the row set and
 * would put the count and the table out of step the moment the two came from different questions.
 */

import type { Locator, Page } from "@playwright/test";

import { test, expect, usingFixture } from "./harness.ts";
import type { ApiClient } from "../src/api/client.ts";
import type { Areas, Tasks } from "../src/api/schemas.ts";
import { dateIn, MONDAY, utcMidnightOn } from "../src/api/weeks.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { solveAndSettle } from "../src/harness/week.ts";
import { declareTask } from "../src/seed/declarations.ts";
import { DISCRETIONARY_MINUTES } from "../src/seed/fixtures/tight-capacity.ts";

usingFixture("tight_capacity");

/* NOT serial, deliberately, and each case establishes what it needs for itself. The two observations are about
 * one screen but they are not a sequence: the second narrows the table the first measured, and in a serial file a
 * failure in the first would report nothing at all about the control. `b1-s34-floors-and-unallocated.spec.ts` is
 * the same shape for the same reason. */

/** What the screen reads before a reader narrows anything, which is what the rendered table is crossed against. */
const OPEN = "/api/v1/tasks?status=open";

/** The same question with the standing narrowed, which is the request the select is expected to produce. */
const OPEN_AND_MARKED = "/api/v1/tasks?status=open&atRisk=true";

/** The standing the filter select narrows to, as the option's own label. */
const AT_RISK_OPTION = "At risk";

/** The smallest piece the solver may place, and the overhang that puts the demand below past reach. */
const CHUNK_MINUTES = 90;

/* THE MARKED ROW IS DECLARED BY THIS FILE RATHER THAN INHERITED FROM THE FIXTURE, and the reason is measured
 * rather than stylistic. `tight_capacity`'s own deadline falls in the PLAN week, while the marking reads the
 * CURRENT week's verdict, and the capacity a week has before an instant beyond its own end is its whole remaining
 * span. Early in the week that span is larger than the work due, so the plan week reports the gap and the current
 * week reports none: measured on a Tuesday, the backlog marks nothing at all, and it marks that same row late in
 * the week. A case about the row treatment cannot be a case that only runs on a Saturday.
 *
 * So it declares work no week could hold before its own deadline. The deadline is the instant the current week
 * ENDS, so the capacity before it is that week's whole remaining span and nothing else, and the demand is one
 * chunk more than the whole of that span, taken from the fixture's own figure so a change to the frame moves both
 * together. Which Area it is filed in does not matter, because no Area's share of the week could hold it either.
 * `owes_more_than_a_week` is the fixture that states this same shape, for the same reason. */
const UNMEETABLE_TASK = "Dissertation chapter";
const UNMEETABLE_MINUTES = DISCRETIONARY_MINUTES + CHUNK_MINUTES;

interface RenderedRow {
  /** The first data cell, which the backlog draws the task's title in. */
  readonly title: string | null;
  readonly isMarked: boolean;
  /** What the reserved mark cell says to a reader who cannot see the mark. */
  readonly standing: string | null;
}

/* Every row the table drew: the title it names, whether it carries the mark attribute, and the words the mark
 * cell says. A STRING because the harness's tsconfig carries no DOM lib, which is why the readers in
 * `s17-capture-from-an-unfillable-slot.spec.ts` and `s21-keyboard-and-focus.spec.ts` are strings too.
 *
 * Both cells are read as ABSENT rather than dereferenced, so a table that stopped drawing the mark column at all
 * fails at the assertion that names it instead of throwing inside this expression. */
const RENDERED_ROWS = `[...document.querySelectorAll('table tbody tr.table__row')].map((row) => ({
  title: row.querySelector('td:not(.table__mark)')?.textContent ?? null,
  isMarked: row.hasAttribute('data-at-risk'),
  standing: row.querySelector('td.table__mark .sr-only')?.textContent ?? null,
}))`;

const ROWS = "table tbody tr.table__row";

const titlesOf = (rows: readonly RenderedRow[]): readonly (string | null)[] =>
  rows.map((row) => row.title).toSorted();

/** One of the band's two figures, found by the eyebrow above it rather than by its place in the strip. */
const figureLabelled = (page: Page, label: string): Locator =>
  page
    .locator(".stat-cell")
    .filter({ has: page.locator(`.stat-cell__label:text-is("${label}")`) })
    .locator(".stat-cell__figure");

/** Declare the unmeetable work, unless a case that ran earlier in this file already did. */
const declareTheUnmeetableWork = async (api: ApiClient): Promise<void> => {
  const open = await api.get<Tasks>(OPEN);
  if (open.tasks.some((task) => task.title === UNMEETABLE_TASK)) return;

  const areas = await api.get<Areas>("/api/v1/areas");
  const area = areas.areas[0];
  expect(area, "the fixture declared no Area to file work in").toBeDefined();
  await declareTask(api, {
    title: UNMEETABLE_TASK,
    areaId: area!.id,
    estimateMinutes: UNMEETABLE_MINUTES,
    minChunkMinutes: CHUNK_MINUTES,
    deadline: utcMidnightOn(dateIn(planWeek(), MONDAY)),
  });
};

/** The backlog as the screen asks for it, with the marked and unmarked titles the rendering is compared against. */
const backlogAsRead = async (
  api: ApiClient,
  path: string = OPEN,
): Promise<{
  readonly all: readonly string[];
  readonly marked: readonly string[];
  readonly unmarked: readonly string[];
}> => {
  const read = await api.get<Tasks>(path);
  return {
    all: read.tasks.map((task) => task.title),
    marked: read.tasks.filter((task) => task.atRisk).map((task) => task.title),
    unmarked: read.tasks.filter((task) => !task.atRisk).map((task) => task.title),
  };
};

/* The premise every assertion below needs, asserted rather than assumed: the week marks at least one open task and
 * leaves at least one unmarked. Without the first, a screen that marked nothing satisfies every set comparison
 * here; without the second, a screen that marked everything satisfies them and the narrowing narrows to the whole
 * table. The declared work supplies the first, and the fixture's two tasks that carry no deadline supply the
 * second: a gap names a task through its own deadline, so a task with none can never be named. */
const assertTheMarkingDiscriminates = (
  marked: readonly string[],
  unmarked: readonly string[],
): void => {
  expect(
    marked,
    "no open task is at risk, so a screen marking nothing would satisfy every comparison here",
  ).not.toEqual([]);
  expect(
    unmarked,
    "every open task is at risk, so a screen marking everything would satisfy every comparison here",
  ).not.toEqual([]);
};

test("the backlog marks exactly the tasks the verdict names, says so in words, and states their count", async ({
  api,
  page,
}) => {
  await declareTheUnmeetableWork(api);
  await solveAndSettle(api, planWeek());
  const read = await backlogAsRead(api);
  assertTheMarkingDiscriminates(read.marked, read.unmarked);

  await page.goto("/backlog");
  await expect(page.locator(ROWS).first()).toBeVisible();
  expect(page.url(), "the backlog redirected to sign-in").not.toContain("/sign-in");

  const rows = (await page.evaluate(RENDERED_ROWS)) as RenderedRow[];

  // THE TABLE IS THE READ, row for row. A screen drawing some other set of tasks is not the screen the figures
  // below are about, and a comparison over the marks alone would not notice.
  expect(titlesOf(rows)).toEqual([...read.all].toSorted());

  // THE OBSERVATION, as set equality both ways. One direction catches a mark on a row the verdict does not name;
  // the other catches a row it names that the screen draws as ordinary. Neither is reachable by searching for the
  // rows expected to be marked and stopping there.
  const marked = rows.filter((row) => row.isMarked);
  expect(titlesOf(marked)).toEqual([...read.marked].toSorted());

  // AND THE SECOND CHANNEL AGREES WITH THE ATTRIBUTE. The mark cell is reserved on every row and says the standing
  // in words, so a treatment that drew the glyph and said nothing would leave a reader who cannot see it with no
  // reading at all. Containment rather than equality: a row that is overdue as well says both.
  for (const row of marked) {
    expect(
      row.standing,
      `${row.title ?? "a row with no title"} carries the mark and says nothing`,
    ).toContain("at risk");
  }
  for (const row of rows.filter((each) => !each.isMarked)) {
    expect(
      row.standing ?? "",
      `${row.title ?? "a row with no title"} carries no mark and says it is at risk`,
    ).not.toContain("at risk");
  }

  // THE HEADER FIGURE IS THE COUNT OF THE MARKED ROWS. It is the server's own count over the same population, so
  // this is the pair that cannot disagree: a figure and a row set that came from two different readings is exactly
  // what a determination made in the client would produce.
  await expect(figureLabelled(page, "at risk")).toHaveText(String(marked.length));
});

test("choosing the at-risk standing narrows the table to those rows, and the band still counts the backlog", async ({
  api,
  page,
}) => {
  await declareTheUnmeetableWork(api);
  await solveAndSettle(api, planWeek());
  const read = await backlogAsRead(api);
  assertTheMarkingDiscriminates(read.marked, read.unmarked);

  await page.goto("/backlog");
  await expect(page.locator(ROWS)).toHaveCount(read.all.length);
  expect(page.url(), "the backlog redirected to sign-in").not.toContain("/sign-in");

  /* Every read the screen makes from here on, recorded before the control is driven: this case is as much about
   * WHERE the narrowing happened as about the rows it left. */
  const asked: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "GET") return;
    const url = new URL(request.url());
    asked.push(`${url.pathname}${url.search}`);
  });

  // THE SCREEN'S OWN CONTROL, driven the way a reader drives it. `exact` is load-bearing: an accessible name is
  // matched as a substring, and "Not at risk" is the option this case must not choose.
  await page.getByLabel("Standing").click();
  await page.getByRole("option", { exact: true, name: AT_RISK_OPTION }).click();

  // THE OBSERVATION: exactly the marked rows, which is fewer than the table held. The count settles first, so the
  // read below is taken from the narrowed table rather than from the one on screen when the select closed.
  await expect(page.locator(ROWS)).toHaveCount(read.marked.length);
  const narrowed = (await page.evaluate(RENDERED_ROWS)) as RenderedRow[];
  expect(titlesOf(narrowed)).toEqual([...read.marked].toSorted());
  expect(narrowed.filter((row) => !row.isMarked)).toEqual([]);

  // AND THE NARROWING WAS ASKED OF THE API rather than applied to the list the screen was already holding. The
  // determination is the verdict's, so a client narrowing a list of its own would be making a second one.
  expect(
    asked.filter((each) => each.startsWith("/api/v1/tasks?") && each.includes("atRisk=true")),
    `the select narrowed the table without asking the api for the marked rows. It read: ${asked.join(", ")}`,
  ).not.toEqual([]);

  // The api answers that question with the same set, which is what makes the rendered narrowing a reading of the
  // server's determination rather than a coincidence between two shorter lists.
  const served = await backlogAsRead(api, OPEN_AND_MARKED);
  expect([...served.all].toSorted()).toEqual([...read.marked].toSorted());

  // THE BAND COUNTS THE BACKLOG AND THE TABLE COUNTS THE ROWS, which is the difference a narrowing makes visible:
  // the open figure is over every open task whatever the filter selects, while the table now holds fewer rows than
  // that. A band that counted its own rows would read as the narrowed figure here.
  await expect(figureLabelled(page, "open tasks")).toHaveText(String(read.all.length));
  await expect(figureLabelled(page, "at risk")).toHaveText(String(read.marked.length));
});
