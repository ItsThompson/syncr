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
 * WHICH OF THE TWO AMBER NOTICE SURFACES THIS FILE REACHES, because the answer is one of each. A
 * browser pass over the weekly session names both, and singles out the PROMOTION panel as the likeliest
 * place it finds something, since it puts a `Table` inside a notice surface and nothing else in the
 * product does. That panel is NOT reached: it returns null on an empty candidate list and no fixture
 * here raises a promotion. The RAISED panel is, and the case at the foot of this file asserts both
 * facts, so the day a fixture raises a promotion it reddens. The composition itself waits on a fixture
 * that raises one.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Page } from "@playwright/test";
import { beyondHorizonWeek, planWeek } from "../src/harness/subject-weeks.ts";

usingFixture("reference_week");

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
  // The weekly session, where both amber notice surfaces live. The raised panel renders here and
  // is asserted below; the promotion panel does not, because no fixture raises a promotion.
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

/* WHICH OF THE TWO AMBER NOTICE SURFACES THESE CASES ACTUALLY REACH, asserted rather than assumed.
 *
 * The promotion panel is the likeliest place a browser pass finds something, because it puts a `Table`
 * INSIDE a notice surface and nothing else in the product does. Adding the session route to the list
 * above does not reach that composition: `PromotionPanel` returns null on an empty candidate list, and
 * no fixture here raises a promotion, which needs repeated pins across three weeks. Measured on this
 * fixture's session payload: `promotions: 0`, `raised: 1`.
 *
 * So this case states which is which, and it is written to fail if either fact changes: the day a fixture
 * raises a promotion, its second half goes red and the gap table has to be corrected. */
test("the weekly session renders the raised panel, and not the promotion panel, which no fixture raises", async ({
  api,
  page,
}) => {
  const week = planWeek();
  const session = await api.get<{
    raised: readonly unknown[];
    promotions: readonly unknown[];
  }>(`/api/v1/reviews/week/${week}`);

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

  expect(
    session.promotions.length,
    "a promotion is raised now, so the promotion panel renders and this case's second half is stale",
  ).toBe(0);
  await expect(page.getByLabel("Repeated pins")).toHaveCount(0);
});
