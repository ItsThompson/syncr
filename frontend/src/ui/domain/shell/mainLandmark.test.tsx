/* The main landmark's two halves: the fragment target, and the focus target that makes it work.
 *
 * A FRAGMENT MOVES FOCUS ONLY BECAUSE OF `tabindex`. A browser navigates to `#main` whether or not the
 * landmark carries one, and the URL gains the fragment either way, but it sets the focus to the landmark
 * only when the landmark is a focusable area, which a `<main>` is not by default. Measured in headless
 * Chromium 151, on a page carrying this landmark's markup, a `href="#main"` link and the built
 * stylesheet: with the attribute, a trusted `Tab` then `Enter` leaves `document.activeElement` on
 * `MAIN#main`; without it, the URL reads `#main` and `document.activeElement` is `BODY`, and a direct
 * `focus()` call is refused there too.
 *
 * THE ATTRIBUTE IS WHAT THESE READ, AND NOT THE PROPERTY. `element.tabIndex` answers -1 on a `<main>`
 * that carries no attribute at all, in Chromium and in jsdom alike, so a case asserting the property
 * passes on exactly the markup it exists to refuse.
 *
 * THE RING IS READ OUT OF THE ARTIFACT A BROWSER DOWNLOADS, because the question is which rule wins on
 * an element, and jsdom applies no stylesheet: `getComputedStyle` on the landmark reports nothing and an
 * assertion over it would pass on a deleted rule. Every selector that paints an outline is asked whether
 * it reaches the landmark, through jsdom's own selector engine, with the focus state satisfied by
 * construction. Chromium matches `:focus-visible` on a programmatically focused element, so the rule that
 * draws the ring for anything focusable is a rule that reaches this landmark. */

import { describe, expect, it } from "vitest";
import { parse } from "postcss";
import { screen } from "@testing-library/react";

import { buildStylesheets } from "../../../../scripts/check-bundle/build.ts";
import { renderSignedInAt } from "../../../testing/renderRoute";

/** A pseudo-class every element matches, standing in for the focus state a rule selects on. */
const IN_THE_FOCUS_STATE = ":not(#no-such-element)";
const FOCUS_PSEUDO_CLASS = /:focus-visible|:focus/g;

/* Firefox's own focus-ring reset, which Tailwind's preflight ships. jsdom's selector engine cannot
 * parse a vendor pseudo-class, and the ring measurement above is Chromium's, so this one selector is
 * named rather than judged. Any other selector this reader cannot judge is a finding. */
const UNJUDGED_BY_THIS_READER = ":-moz-focusring:where(:not(iframe))";

/** The one rule in the artifact that draws the ring for anything focusable. */
const RING_FOR_ANYTHING_FOCUSABLE = ":focus-visible";

const landmark = (): HTMLElement => screen.getByRole("main");

/* THE LANDMARK IS THE SHELL'S AND NOT A SCREEN'S, so every case below renders the one shell screen that
 * reads nothing: the no-match surface. A screen with reads would make these cases wait on stubs that have
 * no bearing on the landmark, and the ring census holds a render open across a build. */
const NO_SCREEN_ANSWERS_THIS = "/nowhere";

async function renderShell(): Promise<HTMLElement> {
  return renderSignedInAt(NO_SCREEN_ANSWERS_THIS);
}

/* ONE build for the file, as the bundle gate's own suite does it: `write: false`, so nothing is left
 * behind and no stale `dist/` can be read. */
const built = buildStylesheets().then((stylesheets) =>
  stylesheets.map((stylesheet) => stylesheet.css).join("\n"),
);

/** Every selector in the artifact that paints an outline, whatever the rest of its rule declares. */
function ringSelectorsIn(css: string): readonly string[] {
  const selectors = new Set<string>();
  parse(css).walkRules((rule) => {
    rule.walkDecls((declaration) => {
      if (declaration.prop.startsWith("outline")) selectors.add(rule.selector);
    });
  });
  return [...selectors];
}

type Reach = "reaches" | "does not reach" | "unreadable";

function reachOf(element: Element, selector: string): Reach {
  const inFocus = selector.replace(FOCUS_PSEUDO_CLASS, IN_THE_FOCUS_STATE);
  try {
    return element.matches(inFocus) ? "reaches" : "does not reach";
  } catch {
    return "unreadable";
  }
}

function selectorsBy(reach: Reach, element: Element, selectors: readonly string[]): string[] {
  return selectors.filter((selector) => reachOf(element, selector) === reach).toSorted();
}

describe("the main landmark", () => {
  it("carries the fragment target a skip link points at", async () => {
    await renderShell();

    expect(landmark()).toHaveAttribute("id", "main");
  });

  it("carries the tabindex that makes it a focusable area", async () => {
    await renderShell();

    expect(landmark()).toHaveAttribute("tabindex", "-1");
  });

  it("takes focus off the navigation row that had it", async () => {
    await renderShell();
    const row = screen.getByRole("link", { name: "backlog" });
    row.focus();
    expect(document.activeElement).toBe(row);

    landmark().focus();

    expect(document.activeElement).toBe(landmark());
  });

  /* THE READING FOLLOWS FOCUS RATHER THAN REPORTING THE LAST THING ASKED FOR. A case that only shows
   * focus arriving on the landmark passes on a document where nothing else could hold it. */
  it("gives focus up again to a control that takes it", async () => {
    await renderShell();
    const row = screen.getByRole("link", { name: "backlog" });
    landmark().focus();
    expect(document.activeElement).toBe(landmark());

    row.focus();

    expect(document.activeElement).toBe(row);
  });

  /* THE CANARY ON THE READER. The case above bites only because a landmark without the attribute cannot
   * take focus at all, which is the DOM's rule rather than this repository's. The sidebar is the
   * landmark's sibling and carries no tabindex, so it stands for that rule: if focus lands on it, the
   * engine has stopped refusing a non-focusable element and the case above no longer proves anything. */
  it("shares the shell with a sibling that refuses focus, so the case above rests on the attribute", async () => {
    const sidebar = await renderShell();
    const row = screen.getByRole("link", { name: "backlog" });
    row.focus();

    sidebar.focus();

    expect(sidebar).not.toHaveAttribute("tabindex");
    expect(document.activeElement).toBe(row);
  });
});

describe("the ring on the landmark", () => {
  it("is drawn by the one rule that draws it for anything focusable, and by no second rule", async () => {
    await renderShell();
    const selectors = ringSelectorsIn(await built);

    expect(selectorsBy("reaches", landmark(), selectors)).toEqual([RING_FOR_ANYTHING_FOCUSABLE]);
  });

  /* THE CENSUS'S CONTROL, ON BOTH EDGES. A reader that matched nothing would report an empty set and pass
   * whatever the artifact declared, so the same reading is taken over a control that must have a ring. The
   * pair localises a change as well: a rule that reaches one of the two and not the other shows up here as
   * two different sets. */
  it("reaches a navigation row through that same rule, so an empty reading cannot pass", async () => {
    await renderShell();
    const selectors = ringSelectorsIn(await built);
    const row = screen.getByRole("link", { name: "backlog" });

    expect(selectorsBy("reaches", row, selectors)).toEqual([RING_FOR_ANYTHING_FOCUSABLE]);
  });

  it("leaves exactly one selector this reader cannot judge, and it is Firefox's own reset", async () => {
    await renderShell();
    const selectors = ringSelectorsIn(await built);

    expect(selectorsBy("unreadable", landmark(), selectors)).toEqual([UNJUDGED_BY_THIS_READER]);
  });
});
