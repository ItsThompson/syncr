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
 * Item 51 left a specific prediction for this suite, that the promotion panel inside the weekly session
 * is the likeliest place a browser pass finds something because it puts a `Table` inside a notice
 * surface, which nothing else in the product does. Rendering it at all is the cheap half of acting on
 * that; measuring its composed layout is not this case's job.
 */

import { test, expect, usingFixture } from "./harness.ts";
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
  // The weekly session, which is the composed layout item 51 predicted a browser pass would find
  // something in: it is the one place in the product that puts a Table inside a notice surface.
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

for (const route of routes()) {
  test(`S22 nothing spins on ${route.what}`, async ({ api, page }) => {
    expect(api.sessionCookie.length).toBeGreaterThan(0);
    await page.goto(route.path);
    // NOT `networkidle`. The application holds the SSE stream open for the life of the page, so the
    // network is never idle and waiting for it to be is waiting for the test timeout. What this needs
    // is that the application has rendered, which is a fact about the DOM.
    await page.waitForFunction("document.querySelectorAll('body *').length > 5");

    // THE SESSION HELD, AND THIS IS THE SCREEN THE ROUTE NAMES. Without this, a redirect to sign-in
    // would satisfy every assertion below: a sign-in form has no spinner either, and the case would
    // report a claim about a screen it never reached.
    expect(page.url(), `${route.path} redirected to sign-in`).not.toContain("/sign-in");
    if (route.path !== "/not-a-route") {
      expect(new URL(page.url()).pathname).toBe(route.path.split("?")[0]);
    }

    for (const selector of INDICATOR_SELECTORS) {
      const found = await page.locator(selector).count();
      expect(found, `${selector} matched ${found} element(s) on ${route.path}`).toBe(0);
    }

    const moving = await page.evaluate(MOTION);
    expect(moving, `elements on ${route.path} carry a transition or an animation`).toEqual([]);
  });
}
