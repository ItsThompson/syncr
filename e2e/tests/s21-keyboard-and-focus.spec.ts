/* S21, AND THE THREE ACCESSIBILITY CLAIMS ONLY A BROWSER CAN JUDGE.
 *
 * WHY THIS FILE EXISTS. The unit suite renders in jsdom, which lays nothing out: `getBoundingClientRect` answers
 * zeros, `:focus-visible` never matches, no computed style is available, and forced-colors mode cannot be entered
 * at all. Every claim below is about a COMPOSED, LAID-OUT result, and the two defects a browser pass over this
 * product's forms found were both of exactly that kind: a select list rendering under a dialog's scrim at
 * z-index 40 against 50, visible and unclickable, and a form opening with the caret on its dismiss control so
 * that `n`-then-type typed nothing. Neither was reachable from a green unit suite.
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
import { civilDateIn } from "../src/api/weeks.ts";
import { HOME_ZONE } from "../src/config.ts";
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
 * of the main column, which is higher up the page and further right.
 *
 * SO THE BREAK IS REQUIRED TO CROSS THE COLUMN, not merely to move right. An unconditional up-and-right carve-out
 * hides a genuine backward step inside one column that happens to sit further right, and the DOM already knows
 * where the boundary is: the sidebar's own width, read off the element the shell gives it. A step from inside the
 * sidebar to beyond it is a new column; a step above the previous one that stays on the same side of the boundary
 * is the tab order walking back up the column the reader was in. */
const overlapsVertically = (one: Tabbable, two: Tabbable): boolean =>
  one.top < two.top + two.height && two.top < one.top + one.height;

const isBackwards = (previous: Tabbable, current: Tabbable, columnEdge: number): boolean => {
  if (overlapsVertically(previous, current)) return current.left < previous.left;
  const above = current.top + current.height <= previous.top;
  if (!above) return false;
  const crossedIntoTheMainColumn = previous.left < columnEdge && current.left >= columnEdge;
  return !crossedIntoTheMainColumn;
};

/* Every tier the grid rendered, read off the elements it drew. A STRING for the reason the readers above are
 * strings: the harness's tsconfig carries no DOM lib, because nothing else in it touches a document. */
const TIERS_PRESENT = `[...document.querySelectorAll('.week-block')]
  .map((element) => element.getAttribute('data-tier'))
  .filter((tier) => tier !== null)`;

/* The level the band's zoom segment states as drawn, which is the grid's own answer after its clamp. */
const PICKED_LEVEL = `document.querySelector('[aria-label="Visible hours"] [aria-pressed="true"]')?.textContent ?? null`;

const FOCUSED_TIER = `document.activeElement && document.activeElement.getAttribute('data-tier')`;

const SCREENS = [
  { what: "the week", path: "" },
  { what: "today", path: "/today" },
  { what: "the backlog", path: "/backlog" },
  { what: "the areas screen", path: "/areas" },
  { what: "templates", path: "/templates" },
  { what: "the learned screen", path: "/learned" },
  { what: "settings", path: "/settings" },
] as const;

/* WHERE THE TWO COLUMNS MEET, read off the element the shell gives the sidebar rather than from `--w-sidebar`:
 * what decides whether a tab stop crossed into the main column is where the sidebar actually ends on this render. */
const COLUMN_EDGE = `(() => {
  const sidebar = document.querySelector('[aria-label="Screens"]');
  if (sidebar === null) return 0;
  const box = sidebar.getBoundingClientRect();
  return Math.round(box.right + window.scrollX);
})()`;

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
      const columnEdge = (await page.evaluate(COLUMN_EDGE)) as number;
      expect(
        columnEdge,
        "the sidebar was not found, so no column boundary was read",
      ).toBeGreaterThan(0);

      const backwards: string[] = [];
      for (let index = 1; index < stops.length; index += 1) {
        const previous = stops[index - 1];
        const current = stops[index];
        if (isBackwards(previous, current, columnEdge)) {
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
    const walked = Math.min(stops.length, 12);
    let measured = 0;
    for (let index = 0; index < walked; index += 1) {
      await page.keyboard.press("Tab");
      const ring = (await page.evaluate(RING)) as Ring | null;
      /* A NULL READING IS A TAB THAT LANDED ON `document.body`, which is one of the adversarial cases this file
       * exists for: a browser pass measured Radix doing exactly that after a keystroke-opened dialog. Skipping it
       * and asserting an empty finding list would let a walk that measured NOTHING pass, so the count is asserted
       * below and a stop with no element is a finding of its own. */
      if (ring === null) {
        missing.push(`tab stop ${String(index + 1)} landed on nothing focusable`);
        continue;
      }
      measured += 1;
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
    expect(measured, "the walk measured fewer rings than it took steps").toBe(walked);
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

    /* THE VIEWPORT IS THE REFERENCE DISPLAY, because which tiers render is a function of the height
     * the grid measures, and the suite's own default measures too shallow to draw any tier below the
     * compact one: at 1280x720 the grid's offered height puts the zoom cap at a single level where
     * even the fifteen-minute frame blocks fall under 8px. On the 1440x900 display whose arithmetic
     * `tokens.css` documents, the cap leaves several levels available and the shallowest of them
     * draws those same blocks in the 8-to-13px band. Pinning it here is what makes the sliver tier a
     * state this session can reach rather than one it reads about. */
    await page.setViewportSize({ width: 1440, height: 900 });
    await render(page, "/today");

    /* NAVIGATION IS A CHORD, and `g` then `w` is what the shell binds. Reaching the week this way is the first
     * half of the claim: a session that had to be started with a click is not a keyboard session. */
    await page.keyboard.press("g");
    await page.keyboard.press("w");
    await page.waitForURL(/\/week/);

    await page.goto(week());
    await page.waitForFunction("document.querySelectorAll('.week-block').length > 0");

    /* THE SLIVER TIER IS ASSERTED, NOT REPORTED. The walk presses `z`, sampling the tiers each
     * level draws, and ends when a press moves nothing: the range's end is reached when the drawn
     * level stops changing, whether that is a wrap to the shallowest level or a clamp holding the
     * deepest one. A fixed press count would be a claim about this week's stored zoom rather than
     * about the product; the unmoved press is the walk's own definition of "the whole range".
     */
    const firstLevel = (await page.evaluate(PICKED_LEVEL)) as string | null;
    expect(
      firstLevel,
      "the band stated no drawn level, so there is nothing to walk",
    ).not.toBeNull();
    const tiersPresent = new Set<string>();
    let level = firstLevel;
    for (let step = 0; step < 24 && level !== null; step += 1) {
      for (const tier of (await page.evaluate(TIERS_PRESENT)) as string[]) {
        tiersPresent.add(tier);
      }
      await page.keyboard.press("z");
      /* Wait for the DRAWN LEVEL to move rather than for a painted guess: a press that changed
       * nothing would read the same tiers twice and hide the wrap forever. A press that moves
       * nothing at all means this display offers one level; the walk ends there and the assertion
       * below says what was missed, because a shallow display is exactly the case that hides the
       * short tiers. */
      const moved = await page
        .waitForFunction(
          `document.querySelector('[aria-label="Visible hours"] [aria-pressed="true"]')?.textContent !== ${JSON.stringify(level)}`,
        )
        .then(() => true)
        .catch(() => false);
      if (!moved) break;
      level = (await page.evaluate(PICKED_LEVEL)) as string | null;
    }
    expect(
      [...tiersPresent],
      "no zoom level offered by this display drew a block below the compact tier; " +
        "the display the session runs at measures too shallow for the short blocks",
    ).toContain("sliver");

    /* Traversal by `j` moves selection AND focus, which is what makes a small block operable: the ring lands on
     * it and a screen reader reads its name. The walk ends on the tier the scenario names: focus is
     * asserted to LAND on a block drawn in the 8-to-13px band, not merely to pass over the tiers on
     * its way down the column. */
    let focusedTier: string | null = null;
    for (let press = 0; press < 80; press += 1) {
      await page.keyboard.press("j");
      focusedTier = (await page.evaluate(FOCUSED_TIER)) as string | null;
      if (focusedTier === "sliver") break;
    }

    expect(focusedTier, "j did not land focus on a sliver-tier block").toBe("sliver");

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

    /* CAPTURE IS GLOBAL, and the caret has to be in the field: a browser pass measured a form opening with the
     * caret on its dismiss control, so `n`-then-type typed nothing at all. */
    await page.keyboard.press("n");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.type("Read the audit");
    await expect(page.getByRole("dialog").locator("input").first()).toHaveValue("Read the audit");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);

    /* CONFIRM THE DAY WITH `c`, on the screen that owns it.
     *
     * WHAT THIS ASSERTED FIRST, AND WHY IT PROVED NOTHING. `getByText(/confirmed/i)` matched the unconfirmed
     * day's OWN notice, "This day is not confirmed", because "confirmed" is a substring of "unconfirmed": the
     * assertion passed with the key never pressed, measured. A presence that holds before the act is not
     * evidence of the act.
     *
     * So both halves are TRANSITIONS. The request is awaited, so a keystroke that sends nothing times out here
     * rather than passing; and the day is read back over the api, where `confirmedAt` moving off null is what the
     * reader was actually promised. The pin step two blocks up is the model, and it is in the same test.
     */
    await render(page, "/today");
    const date = civilDateIn(HOME_ZONE);
    const unsafe: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") unsafe.push(`${request.method()} ${request.url()}`);
    });
    /* THE KEY AND THE CONTROL APPLY ONE RULE, so waiting for the control is waiting for the rule: `c` is guarded
     * on a day that has arrived and holds a block, which is the same condition that enables this button. Pressing
     * as soon as the document had five elements lost the keystroke intermittently to a ledger whose day read had
     * not landed, measured across three runs, and a keystroke lost to a race is the same defect as one never
     * sent: the assertion this replaced could see neither. */
    await expect(page.getByRole("button", { name: "Confirm the day" })).toBeEnabled();
    const dayBefore = await api.get<{ confirmedAt: string | null; blockCount: number }>(
      `/api/v1/days/${date}`,
    );
    expect(
      dayBefore.confirmedAt,
      "the day is already confirmed, so `c` would assert nothing",
    ).toBeNull();
    expect(dayBefore.blockCount, "`c` is guarded on a day holding a block").toBeGreaterThan(0);

    const confirmSent = page.waitForRequest(
      (request) => request.method() === "POST" && request.url().includes(`/days/${date}/confirm`),
      { timeout: 15_000 },
    );
    await page.keyboard.press("c");
    /* The diagnostic names what the page DID send, because "no confirm request" and "a confirm request for another
     * date" are different failures and a bare timeout tells them apart for nobody. */
    await confirmSent.catch((cause: unknown) => {
      throw new Error(
        `\`c\` sent no confirm for ${date}. Unsafe requests seen: ` +
          `${JSON.stringify(unsafe)} (${String(cause)})`,
      );
    });

    await expect
      .poll(
        async () =>
          (await api.get<{ confirmedAt: string | null }>(`/api/v1/days/${date}`)).confirmedAt,
      )
      .not.toBeNull();
    /* And the screen states the change: the notice that says the day is not confirmed is the one thing that
     * cannot survive the day being confirmed. */
    await expect(page.getByText("This day is not confirmed")).toHaveCount(0);

    /* APPROVE WITH Shift+A.
     *
     * WHAT THIS ASSERTED FIRST, AND WHY IT PROVED NOTHING. It counted `.notice, .week-strip__verdict` and
     * required one: `SummaryStrip` renders `.week-strip__verdict` UNCONDITIONALLY, in a quiet variant when the
     * week has no verdict, so the locator can never be zero on a week screen and the count was 1 before the key
     * was pressed, measured.
     *
     * What is asserted instead is that the keystroke REACHED THE API, by awaiting the request it must send, and
     * that the answer is then stated in words on the screen. A keystroke that did nothing at all fails at the
     * request, which is the failure this catches and previously did not.
     *
     * THE SUCCESS PATH IS UNREACHED ON THIS FIXTURE AND THIS CASE DOES NOT BOUND IT. The week holds no pending
     * proposal here, so the api answers 409 and what runs is the refusal arm, which is a real transition: the
     * notice count goes from 0 to 1. The first version carried a success arm as well, asserting the proposal slot
     * was null -- and the slot is null BEFORE the press, so that arm was an assertion whose subject cannot vary on
     * the fixture that runs it. It is gone rather than left dormant. A 2xx here now REDDENS with what to write,
     * because the day a seed makes the approval land is the day this case has to assert what a landed approval
     * changes, and the fixture that makes it land is what records the coupling.
     */
    await render(page, week());
    /* The same determinism as the confirm step: the screen's own approve control exists once the week has arrived,
     * and the binding it shares is wired by the same reading. */
    await expect(page.getByRole("button", { name: /Approve/ })).toBeVisible();
    const noticesBefore = await page.locator(".notice").count();
    const approveSent = page.waitForRequest(
      (request) =>
        request.method() === "POST" && request.url().includes(`/weeks/${isoWeek}/approve`),
      { timeout: 15_000 },
    );
    await page.keyboard.press("Shift+A");
    const approve = await approveSent.catch((cause: unknown) => {
      throw new Error(
        `\`Shift+A\` sent no approval for ${isoWeek}. Unsafe requests seen: ` +
          `${JSON.stringify(unsafe)} (${String(cause)})`,
      );
    });
    const answered = await approve.response();
    const status = answered === null ? 0 : answered.status();

    expect(
      status,
      "the approval was answered 2xx, so the success path is now reachable on this fixture and this " +
        "case does not bound it: assert what a landed approval changes -- the proposal slot clearing and " +
        "a new revision -- rather than leaving the branch unwritten. Ticket 1561 owns the fixture.",
    ).toBeGreaterThanOrEqual(400);
    /* The refusal is stated in words, which is the transition: the week screen carried no notice before the press. */
    await expect.poll(async () => page.locator(".notice").count()).toBeGreaterThan(noticesBefore);
  });
});
