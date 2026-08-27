/* The skip link's contract, on every screen the shell mounts.
 *
 * FIRST FOCUSABLE IS READ OUT OF THE LIVE DOM, not out of the component tree: a link that renders
 * anywhere but ahead of the top bar and sidebar fails here even though every other assertion about
 * it would still pass. The nine paths are the seven navigation screens plus `/setup` and the
 * not-found surface, which is the whole set of routes the gate's shell wraps.
 *
 * THE TREATMENT IS READ OUT OF THE ARTIFACT A BROWSER DOWNLOADS, because jsdom applies no stylesheet:
 * `getComputedStyle` on the link reports nothing and an assertion over it would pass on a deleted rule.
 *
 * THE MARKUP HALF OF THE SPELLING RULE IS PINNED BY CLASS-NAME EXACTNESS. `scripts/check-channels`
 * silently skips a variant utility it does not recognize in markup while reporting an unplaceable CSS
 * declaration, so only one of the two spellings is enforceable by the gate; this file refuses the
 * unenforceable one outright, and the artifact cases below refuse a treatment that stops being a
 * declaration under `:focus-visible`. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildStylesheets } from "../../../../scripts/check-bundle/build.ts";
import { apiServer } from "../../../testing/apiServer";
import { readyz } from "../../../testing/apiStub";
import { renderSignedInAt } from "../../../testing/renderRoute";
import { SCREENS, SETUP_PATH } from "./navigation";

const SKIP_LINK_NAME = "Skip to content";

/* The seven navigation screens, first run, and the catch-all: everything `GatedShell` wraps. */
const SHELL_MOUNTED_PATHS = [...SCREENS.map((nav) => nav.path), SETUP_PATH, "/nowhere"];

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not(:disabled)",
  'input:not(:disabled):not([type="hidden"])',
  "select:not(:disabled)",
  "textarea:not(:disabled)",
  "summary",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function firstFocusableElement(): Element {
  const first = document.body.querySelector(FOCUSABLE_SELECTOR);
  if (first === null) throw new Error("the screen mounts nothing focusable");
  return first;
}

/* ONE build for the file, `write: false`, as the bundle gate's own suite does it. */
const built = buildStylesheets().then((stylesheets) =>
  stylesheets.map((stylesheet) => stylesheet.css).join("\n"),
);

async function restRule(): Promise<string> {
  const rule = /\.skip-link\s*\{([^}]*)\}/.exec(await built);
  if (rule === null) throw new Error("the built stylesheet declares no .skip-link rule");
  return rule[1];
}

async function revealRule(): Promise<string> {
  const rule = /\.skip-link:focus-visible\s*\{([^}]*)\}/.exec(await built);
  if (rule === null)
    throw new Error("the built stylesheet declares no .skip-link:focus-visible rule");
  return rule[1];
}

describe("the skip link", () => {
  it.each(SHELL_MOUNTED_PATHS)("mounts as the first focusable stop on %s", async (path) => {
    apiServer.use(readyz());
    await renderSignedInAt(path);

    const link = screen.getByRole("link", { name: SKIP_LINK_NAME });
    expect(link).toHaveAttribute("href", "#main");
    expect(firstFocusableElement()).toBe(link);
  });

  /* THE ACTIVATION HALF IS THE BROWSER'S OWN RULE, and jsdom cannot be trusted to play it: following
   * even a same-document fragment link makes jsdom tear the document down, so a click-based case would
   * measure the runner and not the product. `mainLandmark.test.tsx` measures the move in headless
   * Chromium and holds the landmark to both halves of it -- the fragment target and the tabindex that
   * makes focusing it legal -- so what is left to pin here is that THIS link aims at THAT landmark. */
  it("aims at the landmark that carries the tabindex making a fragment focus legal", async () => {
    apiServer.use(readyz());
    await renderSignedInAt("/week");

    const link = screen.getByRole("link", { name: SKIP_LINK_NAME });
    expect(link).toHaveAttribute("href", "#main");
    const target = document.getElementById("main");
    expect(target).not.toBeNull();
    expect(target).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("main")).toBe(target);
  });

  it("reaches the reader as the bare class name, carrying no variant utility", async () => {
    apiServer.use(readyz());
    await renderSignedInAt("/week");

    expect(screen.getByRole("link", { name: SKIP_LINK_NAME }).className).toBe("skip-link");
  });
});

describe("the treatment in the built stylesheet", () => {
  it("clips the link to the token layer's hidden box at rest", async () => {
    const atRest = await restRule();

    expect(atRest).toMatch(/position:\s*absolute/);
    expect(atRest).toMatch(/width:\s*var\(--state-hidden-size\)/);
    expect(atRest).toMatch(/height:\s*var\(--state-hidden-size\)/);
    expect(atRest).toMatch(/clip-path:\s*var\(--state-hidden-clip\)/);
  });

  it("restores geometry under :focus-visible and under nothing else", async () => {
    const reveal = await revealRule();

    expect(reveal).toMatch(/width:\s*auto/);
    expect(reveal).toMatch(/height:\s*auto/);
    expect(reveal).toMatch(/overflow:\s*visible/);
    expect(reveal).toMatch(/clip-path:\s*none/);
  });

  it("declares no transition or animation, in either half", async () => {
    for (const rule of [await restRule(), await revealRule()]) {
      expect(rule).not.toMatch(/transition|animation/);
    }
  });

  /* Forced colors strips pigment, not geometry. A treatment that spent a colour to be seen would
   * vanish exactly where it has to work; these two rules therefore spend none. */
  it("spends no pigment, so forced colors strips nothing the control needs", async () => {
    for (const rule of [await restRule(), await revealRule()]) {
      expect(rule).not.toMatch(/\b(background|color|border)\b\s*:/);
    }
  });

  it("declares no outline, leaving base.css's ring the only painter", async () => {
    for (const rule of [await restRule(), await revealRule()]) {
      expect(rule).not.toMatch(/\boutline\b\s*:/);
    }
  });
});
