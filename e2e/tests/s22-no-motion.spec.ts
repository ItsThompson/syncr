/* S22: nothing spins.
 *
 * The one browser scenario in this file, and the reason it is worth a browser is that the repository's
 * existing motion gate reads the BUILT STYLESHEET, declaration by declaration. That input cannot see a
 * transition an inline style adds, one a third-party component injects at runtime, or a spinner that is
 * a DOM element rather than a CSS rule. This reads the COMPUTED style of every element the live
 * application actually rendered, which is the one input the eight static checks do not have.
 *
 * The states are exercised rather than assumed: every one of the shell's routes, both weekly-session
 * modes, a week whose plan is beyond the horizon and therefore empty, and a route that does not exist.
 *
 * WHICH OF THE TWO AMBER NOTICE SURFACES THIS FILE REACHES, because the answer is one of each, and
 * now on one fixture each. The file's fixture is `repeated_pins`: the reference week plus one content
 * pinned to one local time in three consecutive weeks beyond it, which is what makes a promotion
 * candidate exist at all. The RAISED panel is read on the plan week's session, whose review window
 * ends before any pin was made. The PROMOTION panel -- the one composition that puts a `Table`
 * inside a notice surface, and so the likeliest place a browser pass finds something -- is read on
 * the later week whose window holds the pins, and it is measured from the boxes the two compose
 * rather than from a class list.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Page } from "@playwright/test";
import { beyondHorizonWeek, planWeek } from "../src/harness/subject-weeks.ts";
import { promotionSessionWeek } from "../src/seed/fixtures/repeated-pins.ts";

usingFixture("repeated_pins");

/* What a spinner, a skeleton or a progress bar is called, in the vocabularies something might use. A
 * match is a finding rather than a false positive: this product has no loading indicator of any kind. */
const INDICATOR_SELECTORS = [
  '[role="progressbar"]',
  "progress",
  '[aria-busy="true"]',
  '[class*="spinner" i]',
  '[class*="skeleton" i]',
  '[class*="loader" i]',
  '[class*="animate-" i]',
  '[class*="pulse" i]',
];

/* Passed as a STRING and wrapped as a call, deliberately. The harness's tsconfig carries no DOM lib,
 * because nothing else in it touches a document, and `page.evaluate` given a string evaluates it as an
 * EXPRESSION: a bare arrow function would be returned rather than run. */
const MOTION = `(() => {
  const moving = [];
  for (const element of document.querySelectorAll("*")) {
    const style = getComputedStyle(element);
    const transition = style.transitionDuration.split(",").map((each) => each.trim());
    const animation = style.animationName;
    const moves = transition.some((duration) => duration !== "0s") || (animation && animation !== "none");
    if (moves) {
      moving.push(element.tagName.toLowerCase() + "." + element.className + " transition=" +
        style.transitionDuration + " animation=" + animation);
    }
  }
  return moving.slice(0, 10);
})()`;

const routes = (): readonly { readonly what: string; readonly path: string }[] => [
  { what: "a week that holds a plan", path: `/week?week=${planWeek()}` },
  { what: "a week beyond the horizon", path: `/week?week=${beyondHorizonWeek()}` },
  // The weekly session of the PLAN week. Both amber notice surfaces live in session mode; this
  // route's review window ends before any pin was made, so the raised panel renders here and is
  // asserted below, and the promotion panel does not. The case that reads that panel opens the
  // session four weeks past the plan week, where the pins fall inside the window.
  { what: "the weekly session", path: `/week?week=${planWeek()}&mode=session` },
  { what: "the areas screen in weekly mode", path: "/areas?mode=weekly" },
  { what: "today", path: "/today" },
  { what: "the backlog", path: "/backlog" },
  { what: "the areas screen", path: "/areas" },
  { what: "the templates screen", path: "/templates" },
  { what: "the settings screen", path: "/settings" },
  { what: "the learned screen", path: "/learned" },
  { what: "a route that does not exist", path: "/not-a-route" },
];

/** Open `path`, wait for the application to have rendered, and confirm it is the screen named.
 *
 * NOT `networkidle`. The application holds the SSE stream open for the life of the page, so the network is
 * never idle and waiting for it to be is waiting for the test timeout.
 *
 * The route check is not decoration: without it a redirect to sign-in would satisfy every motion assertion
 * below, because a sign-in form has no spinner either, and the case would report a claim about a screen it
 * never reached. */
const render = async (page: Page, path: string): Promise<void> => {
  await page.goto(path);
  await page.waitForFunction("document.querySelectorAll('body *').length > 5");
  expect(page.url(), `${path} redirected to sign-in`).not.toContain("/sign-in");
  if (path !== "/not-a-route") {
    expect(new URL(page.url()).pathname).toBe(path.split("?")[0]);
  }
};

for (const route of routes()) {
  test(`S22 nothing spins on ${route.what}`, async ({ api, page }) => {
    expect(api.sessionCookie.length).toBeGreaterThan(0);
    await render(page, route.path);

    for (const selector of INDICATOR_SELECTORS) {
      const found = await page.locator(selector).count();
      expect(found, `${selector} matched ${found} element(s) on ${route.path}`).toBe(0);
    }

    const moving = await page.evaluate(MOTION);
    expect(moving, `elements on ${route.path} carry a transition or an animation`).toEqual([]);
  });
}

/* WHICH OF THE TWO AMBER NOTICE SURFACES THESE CASES ACTUALLY REACH, asserted rather than assumed,
 * and on which session. The raised panel is read on the plan week's session: its review window ends
 * before any pin was made, so the api guard below constrains exactly the input that makes its amber
 * section the only thing the surface could be. The promotion panel is read on a later session whose
 * window holds all three pins, and it is read from rendered geometry: a class list states what an
 * element is called, not whether the table was drawn inside the surface holding it. */
test("the weekly session renders the raised panel", async ({ api, page }) => {
  const week = planWeek();
  const session = await api.get<{ raised: readonly unknown[] }>(`/api/v1/reviews/week/${week}`);

  await render(page, `/week?week=${week}&mode=session`);
  await expect(page.getByText("Weekly session")).toBeVisible();

  expect(
    session.raised.length,
    "the fixture raises nothing, so the panel has nothing to draw",
  ).toBeGreaterThan(0);
  // THE SURFACE, NOT THE LABEL. `RaisedPanel` puts `aria-label="Raised in this session"` on both of its
  // branches, the amber section and the "nothing is outstanding" prose that replaces it, so a label locator
  // is satisfied by either and cannot bound the surface this case is cited for. The API guard above
  // constrains the input, so the only way to reach the prose branch is a frontend regression, which is
  // exactly what a browser pass exists to catch.
  await expect(
    page.locator('section[aria-label="Raised in this session"].notice--amber'),
  ).toBeVisible();
});

/* THE PROMOTION PANEL, READ FROM THE PIXELS. The api guard runs first, so the candidate exists on the
 * wire before any pixel is read: if the payload arrived empty, the case would be about a screen that
 * correctly draws nothing rather than about the composition it exists to bound.
 *
 * The composition is then asserted over rendered geometry -- the table's box inside the notice
 * surface's box, and the candidate's own row inside both -- because the claim here is about LAYOUT:
 * whether the one `Table`-inside-a-notice-surface composition in the product actually composes when a
 * real browser lays it out. A class list states what an element is called, which bounds nothing about
 * where it landed; boxes do. The row assertions keep the geometry honest: containment over an empty
 * table passes, so the row the api named must be among the things contained. */
test("S22 the promotion panel composes its table inside the notice surface", async ({
  api,
  page,
}) => {
  const week = promotionSessionWeek();
  const session = await api.get<{
    promotions: readonly { readonly title: string; readonly consecutiveWeeks: number }[];
  }>(`/api/v1/reviews/week/${week}`);
  const [candidate] = session.promotions;
  expect(
    candidate,
    "the fixture pins one content across three consecutive weeks, so the session names a candidate",
  ).toBeDefined();

  await render(page, `/week?week=${week}&mode=session`);
  await expect(page.getByText("Weekly session")).toBeVisible();

  // THE SURFACE BY ITS LABEL, THE COMPOSITION BY ITS GEOMETRY. The panel sits below the fold on a
  // session this tall, and an off-screen subtree is not guaranteed to be laid out when its box is
  // asked for, so the scroll is what makes the boxes below measurements of the drawn surface. The
  // table carries no visibility assertion of its own: a table that is absent or hidden answers a
  // null box or empties the role locators, and the null-box, containment and row guards below are
  // what redden for that -- a guard that cannot fail before one of those does is not a guard.
  const panel = page.locator('section[aria-label="Repeated pins"]');
  await expect(panel, "the session drew no promotion panel").toBeVisible();
  await panel.scrollIntoViewIfNeeded();
  const table = panel.getByRole("table");

  const panelBox = await panel.boundingBox();
  const tableBox = await table.boundingBox();
  expect(panelBox, "the promotion panel rendered with no box to measure").not.toBeNull();
  expect(tableBox, "the table rendered with no box to measure").not.toBeNull();
  // COMPOSED: every edge of the table lies within the edges of the surface holding it, which is the
  // whole of what "inside" means once the layout has been computed.
  expect(tableBox!.x).toBeGreaterThanOrEqual(panelBox!.x);
  expect(tableBox!.y).toBeGreaterThanOrEqual(panelBox!.y);
  expect(tableBox!.x + tableBox!.width).toBeLessThanOrEqual(panelBox!.x + panelBox!.width);
  expect(tableBox!.y + tableBox!.height).toBeLessThanOrEqual(panelBox!.y + panelBox!.height);

  // THE ROW IS THE CANDIDATE THE API NAMED, drawn within the same box, so the geometry above cannot
  // pass on a table that renders empty. The row is matched on the binding AND the week figure:
  // the refusal sentence this api renders beside the answer also names the binding, so a match on
  // the title alone could be satisfied by prose instead of by the candidate's own cells.
  const row = panel
    .getByRole("row")
    .filter({ hasText: candidate!.title })
    .filter({ hasText: `${candidate!.consecutiveWeeks} weeks` });
  await expect(row, "the table drew no row for the candidate the api named").toHaveCount(1);
  const rowBox = await row.boundingBox();
  expect(rowBox, "the candidate's row rendered with no box to measure").not.toBeNull();
  expect(rowBox!.x).toBeGreaterThanOrEqual(tableBox!.x);
  expect(rowBox!.x + rowBox!.width).toBeLessThanOrEqual(tableBox!.x + tableBox!.width);
  expect(rowBox!.y).toBeGreaterThanOrEqual(tableBox!.y);
  expect(rowBox!.y + rowBox!.height).toBeLessThanOrEqual(tableBox!.y + tableBox!.height);
});
