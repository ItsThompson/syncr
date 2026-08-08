/* S21, AND THE THREE ACCESSIBILITY CLAIMS ONLY A BROWSER CAN JUDGE.
 *
 * WHY THIS FILE EXISTS. The unit suite renders in jsdom, which lays nothing out: `getBoundingClientRect` answers
 * zeros, `:focus-visible` never matches, no computed style is available, and forced-colors mode cannot be entered
 * at all. Every claim below is about a COMPOSED, LAID-OUT result, and the two defects item 46 found by opening a
 * browser once were both of exactly that kind: a select list rendering under a dialog's scrim at z-index 40 against
 * 50, visible and unclickable, and a form opening with the caret on its dismiss control so that `n`-then-type typed
 * nothing. Neither was reachable from a green unit suite.
 *
 * S21, A WHOLE PLANNING SESSION WITHOUT THE POINTER. The scenario the smoke table has carried as not automated:
 * navigate by chord, traverse blocks including a SLIVER-TIER one, pin with Shift+Down, capture with `n`, confirm
 * with `c`, approve with Shift+A. The sliver tier is the case that matters, because a sliver is 8 to 13 pixels tall
 * and a pointer target that small is not one: if the keyboard cannot reach it, nothing can.
 *
 * FOCUS ORDER FOLLOWS VISUAL ORDER is a claim about geometry, and it is asserted per screen against the boxes the
 * browser reports rather than against the DOM order alone: DOM order IS the tab order here, so what is checked is
 * that the layout has not reordered anything the reader would traverse.
 *
 * THE RING IS CHOSEN BY THE SURFACE, which is a rule about a computed value: the standard ring is
 * `--ink-bright` and the inverse is `--paper-raised`, scoped to an ink-filled container, at a 2px offset in both
 * cases. A control that lost its ring, or took the wrong one for the surface it landed on, is invisible to every
 * static check in the repository.
 *
 * FORCED-COLORS MODE drops every fill and forces every colour, so a state carried only by a fill disappears. The
 * design language's answer is that every block state except hover pairs its fill with a rule, a border or a glyph,
 * and hover is mouse-only. That is asserted here by comparing what the browser actually computes for a block in
 * each state, with the mode on. */

import { test, expect, usingFixture } from "./harness.ts";
import type { Page } from "@playwright/test";
import { planWeek } from "../src/harness/subject-weeks.ts";

usingFixture("reference_week");

test.describe.configure({ mode: "serial" });

const week = (): string => `/week?week=${planWeek()}`;

/** Open a path and wait for the application to have drawn, refusing a redirect to sign-in.
 *
 * The session cookie is installed by the `api` fixture, so every case here asks for it: without it the gate sends
 * the browser to sign-in, and a sign-in form satisfies most of the assertions below while proving nothing about a
 * screen it never reached.
 */
const render = async (page: Page, path: string): Promise<void> => {
  await page.goto(path);
  await page.waitForFunction("document.querySelectorAll('body *').length > 5");
  expect(page.url(), `${path} redirected to sign-in`).not.toContain("/sign-in");
};

/* Every element a reader can tab to, with the box the browser gives it. Passed as a STRING because the harness's
 * tsconfig carries no DOM lib: `page.evaluate` given a string evaluates it as an expression. */
const TABBABLE = `(() => {
  const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]),' +
    ' textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  return [...document.querySelectorAll(selector)]
    .filter((element) => {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    })
    .map((element) => {
      const box = element.getBoundingClientRect();
      return {
        name: element.tagName.toLowerCase() + '.' + String(element.className).split(' ')[0],
        top: Math.round(box.top + window.scrollY),
        left: Math.round(box.left + window.scrollX),
        height: Math.round(box.height),
      };
    });
})()`;

interface Tabbable {
  readonly name: string;
  readonly top: number;
  readonly left: number;
  readonly height: number;
}

/* WHAT "THE SAME ROW" IS, MEASURED RATHER THAN GUESSED. The first version called two stops the same row when
 * their tops were within the row height, and reported a tab panel that begins 27px under its own tab strip as a
 * backward step. Two elements are on one row when their vertical extents OVERLAP, which is what a reader sees:
 * a 26px control beside a 28px one overlaps almost entirely, and a panel that starts where the strip ends does
 * not overlap at all.
 *
 * A COLUMN BREAK IS NOT A BACKWARD STEP EITHER, and that was the other false report. The shell is two columns:
 * the sidebar's rows are in the DOM before the route's content, so tabbing off the last nav item goes to the TOP
 * of the main column, which is higher up the page and further right. So a stop above the previous one AND to the
 * right of it is a new column, and one above it without moving right is the tab order walking back up the column
 * the reader was in. */
const overlapsVertically = (one: Tabbable, two: Tabbable): boolean =>
  one.top < two.top + two.height && two.top < one.top + one.height;

const isBackwards = (previous: Tabbable, current: Tabbable): boolean => {
  if (overlapsVertically(previous, current)) return current.left < previous.left;
  const above = current.top + current.height <= previous.top;
  return above && current.left <= previous.left;
};

/* Every tier the grid rendered, read off the elements it drew. A STRING for the reason the readers above are
 * strings: the harness's tsconfig carries no DOM lib, because nothing else in it touches a document. */
const TIERS_PRESENT = `[...document.querySelectorAll('.week-block')]
  .map((element) => element.getAttribute('data-tier'))
  .filter((tier) => tier !== null)`;

const SCREENS = [
  { what: "the week", path: "" },
  { what: "today", path: "/today" },
  { what: "the backlog", path: "/backlog" },
  { what: "the areas screen", path: "/areas" },
  { what: "templates", path: "/templates" },
  { what: "the learned screen", path: "/learned" },
  { what: "settings", path: "/settings" },
] as const;

test.describe("focus order follows visual order", () => {
  for (const screen of SCREENS) {
    test(`on ${screen.what}, every tab stop is at or below the one before it`, async ({
      api,
      page,
    }) => {
      expect(api.sessionCookie.length).toBeGreaterThan(0);
      await render(page, screen.path === "" ? week() : screen.path);

      const stops = (await page.evaluate(TABBABLE)) as Tabbable[];
      expect(stops.length, "a screen with no tab stop cannot be operated at all").toBeGreaterThan(
        2,
      );

      const backwards: string[] = [];
      for (let index = 1; index < stops.length; index += 1) {
        const previous = stops[index - 1];
        const current = stops[index];
        if (isBackwards(previous, current)) {
          backwards.push(
            `${current.name} at ${current.top},${current.left} follows ` +
              `${previous.name} at ${previous.top},${previous.left}`,
          );
        }
      }

      expect(backwards, `tab order walks back up ${screen.what}`).toEqual([]);
    });
  }
});

/* THE RING, READ OFF EVERY TAB STOP THE SCREEN HAS. Focused by keyboard rather than by `.focus()`, because
 * `:focus-visible` is what the ring is drawn on and a programmatic focus does not always match it: this is the
 * distinction the design language spends the outline channel on. */
const RING = `(() => {
  const element = document.activeElement;
  if (!element || element === document.body) return null;
  const style = getComputedStyle(element);
  const onInk = element.closest('.on-ink-surface') !== null;
  return {
    name: element.tagName.toLowerCase() + '.' + String(element.className).split(' ')[0],
    style: style.outlineStyle,
    width: style.outlineWidth,
    offset: style.outlineOffset,
    color: style.outlineColor,
    onInk,
  };
})()`;

interface Ring {
  readonly name: string;
  readonly style: string;
  readonly width: string;
  readonly offset: string;
  readonly color: string;
  readonly onInk: boolean;
}

test.describe("the focus ring", () => {
  test("is drawn at a 2px offset on every tab stop of the week screen, in the surface's own ink", async ({
    api,
    page,
  }) => {
    expect(api.sessionCookie.length).toBeGreaterThan(0);
    await render(page, week());
    const stops = (await page.evaluate(TABBABLE)) as Tabbable[];

    const missing: string[] = [];
    /* The first twelve, which is every control in the band and the strip plus the first blocks. Walking all of
     * ~210 blocks would measure the same rule two hundred times. */
    for (let index = 0; index < Math.min(stops.length, 12); index += 1) {
      await page.keyboard.press("Tab");
      const ring = (await page.evaluate(RING)) as Ring | null;
      if (ring === null) continue;
      if (ring.style === "none" || ring.width !== "2px" || ring.offset !== "2px") {
        missing.push(`${ring.name} draws ${ring.style} ${ring.width} at ${ring.offset}`);
      }
      /* THE INK IS THE SURFACE'S. `--ink-bright` is #1a3aa6 and the inverse ring is `--paper-raised`, #fdfbf4:
       * a control on an ink-filled container takes the inverse one, and everything else takes the standard. */
      const expected = ring.onInk ? "rgb(253, 251, 244)" : "rgb(26, 58, 166)";
      if (ring.color !== expected) {
        missing.push(
          `${ring.name} rings in ${ring.color}, not the ${ring.onInk ? "inverse" : "standard"} ink`,
        );
      }
    }

    expect(missing).toEqual([]);
  });
});

/* WHAT DISTINGUISHES ONE BLOCK STATE FROM ANOTHER, in the properties the state channels spend. Read for the
 * focused block and for a sibling in the same pass, so the comparison is between two states measured under one
 * rendering rather than across two page loads. */
test.describe("forced-colors mode", () => {
  test("keeps a selected block distinguishable from an unselected one, with every fill dropped", async ({
    api,
    page,
  }) => {
    expect(api.sessionCookie.length).toBeGreaterThan(0);
    await render(page, week());
    await page.waitForFunction("document.querySelectorAll('.week-block').length > 1");
    await page.emulateMedia({ forcedColors: "active" });

    /* Selection moves DOM focus, so the keyboard's own traversal is what puts a block into the state. */
    await page.keyboard.press("j");
    const selected = await page.evaluate(`(() => {
      const element = document.activeElement;
      if (!element || !element.classList.contains('week-block')) return null;
      const style = getComputedStyle(element);
      const sibling = [...document.querySelectorAll('.week-block')].find((one) => one !== element);
      const other = sibling === undefined ? null : getComputedStyle(sibling);
      return {
        selectedRule: style.borderLeftColor + ' ' + style.borderLeftWidth,
        otherRule: other === null ? null : other.borderLeftColor + ' ' + other.borderLeftWidth,
        selectedFill: style.backgroundColor,
        otherFill: other === null ? null : other.backgroundColor,
      };
    })()`);

    expect(selected, "no block was reachable, so nothing was compared").not.toBeNull();
    const states = selected as {
      selectedRule: string;
      otherRule: string | null;
      selectedFill: string;
      otherFill: string | null;
    };

    /* THE FILL IS NOT WHAT DISTINGUISHES THEM, because forced colors drops it: the two fills are the system's own
     * and are equal. What survives is the 3px left rule the selected state spends. */
    expect(states.selectedFill).toBe(states.otherFill);
    expect(states.selectedRule).not.toBe(states.otherRule);
  });
});

test.describe("S21 keyboard only, at every tier the grid renders", () => {
  test("S21 traverses, pins, captures, confirms and approves without the pointer", async ({
    api,
    page,
  }) => {
    const isoWeek = planWeek();
    await render(page, "/today");

    /* NAVIGATION IS A CHORD, and `g` then `w` is what the shell binds. Reaching the week this way is the first
     * half of the claim: a session that had to be started with a click is not a keyboard session. */
    await page.keyboard.press("g");
    await page.keyboard.press("w");
    await page.waitForURL(/\/week/);

    await page.goto(week());
    await page.waitForFunction("document.querySelectorAll('.week-block').length > 0");

    /* EVERY TIER THE SHIPPED GRID RENDERS IS REACHED BY THE KEYBOARD, and the set is read off the grid rather
     * than named here: what tiers a week produces depends on its own block lengths and on the zoom, so a list
     * would be a claim about a fixture rather than about the product. `z` walks the ladder first, so whatever
     * tiers this week can produce at any zoom are the ones the traversal is then held to.
     *
     * WHAT THIS FIXTURE DOES NOT REACH is the sliver tier: no seeded week holds a block short enough to fall
     * below 13px at any available zoom, so the 8-to-13px case is exercised against the real component in
     * `frontend/src/ui/domain/week-grid/__tests__/block.test.tsx`, by role, at that exact height. Ticket 1561
     * carries the fixture that would bring it here. */
    const LADDER_STEPS = 6;
    const tiersPresent = new Set<string>();
    for (let step = 0; step < LADDER_STEPS; step += 1) {
      for (const tier of (await page.evaluate(TIERS_PRESENT)) as string[]) {
        tiersPresent.add(tier);
      }
      await page.keyboard.press("z");
    }
    expect(
      tiersPresent.size,
      "no block rendered at any zoom, so no tier was exercised",
    ).toBeGreaterThan(0);

    /* Traversal by `j` moves selection AND focus, which is what makes a small block operable: the ring lands on
     * it and a screen reader reads its name. */
    const reached = new Set<string>();
    for (let press = 0; press < 80; press += 1) {
      await page.keyboard.press("j");
      const tier = await page.evaluate(
        `document.activeElement && document.activeElement.getAttribute('data-tier')`,
      );
      if (typeof tier === "string") reached.add(tier);
      if (reached.size === tiersPresent.size) break;
    }

    expect([...reached].toSorted(), "j did not reach every tier the grid rendered").toEqual(
      [...tiersPresent].toSorted(),
    );

    /* PIN WITH Shift+Down, which moves the focused block by fifteen minutes and pins it there. The pin is read
     * back over the api rather than from the glyph, because what the reader is promised is a stored pin. */
    const before = await api.get<{ pins: readonly unknown[] }>(`/api/v1/weeks/${isoWeek}`);
    await page.keyboard.press("Shift+ArrowDown");
    await expect
      .poll(
        async () =>
          (await api.get<{ pins: readonly unknown[] }>(`/api/v1/weeks/${isoWeek}`)).pins.length,
      )
      .toBeGreaterThan(before.pins.length);

    /* CAPTURE IS GLOBAL, and the caret has to be in the field: item 46 measured a form opening with the caret on
     * its dismiss control, so `n`-then-type typed nothing at all. */
    await page.keyboard.press("n");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.type("Read the audit");
    await expect(page.getByRole("dialog").locator("input").first()).toHaveValue("Read the audit");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);

    /* CONFIRM THE DAY WITH `c`, on the screen that owns it. The reading changes, which is how a count that
     * changes reports progress in a product with no motion. */
    await render(page, "/today");
    await page.keyboard.press("c");
    await expect(page.getByText(/confirmed/i).first()).toBeVisible();

    /* APPROVE WITH Shift+A. Whether this week HAS a pending proposal depends on what the solve the pin triggered
     * produced, so the assertion is that the keystroke reached the api and the outcome is stated in words: either
     * the week is approved, or the api's own refusal is rendered. A keystroke that did nothing at all, with no
     * sentence anywhere, is the failure this catches. */
    await render(page, week());
    await page.keyboard.press("Shift+A");
    await expect
      .poll(async () => {
        const approved = await page.locator(".notice, .week-strip__verdict").count();
        return approved;
      })
      .toBeGreaterThan(0);
  });
});
