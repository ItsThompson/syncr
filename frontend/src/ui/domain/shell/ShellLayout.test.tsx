/* The shell's composition, and the two rules it exists to hold.
 *
 * The sidebar is PAPER, not ink, and the current item takes the same channel a selected block uses.
 * Both are asserted against the compiled stylesheet rather than against a class name, so a renamed
 * utility that stops producing the fill fails here. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { compileUtilities, declarationsOf, srcDir } from "../../../testing/compileTheme";
import { renderSignedInAt } from "../../../testing/renderRoute";
import { SidebarNav } from "./SidebarNav";
import { SCREENS } from "./navigation";

describe("ShellLayout", () => {
  it("renders the wordmark in the top bar, lowercase", async () => {
    await renderSignedInAt("/week");
    expect(screen.getByText("syncr")).toBeInTheDocument();
  });

  it("renders the notice-strip slot even with nothing in it", async () => {
    await renderSignedInAt("/week");
    expect(screen.getByLabelText("Notices")).toBeEmptyDOMElement();
  });

  it("renders the route inside the shell", async () => {
    await renderSignedInAt("/today");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Today");
  });
});

/* THE PALETTE'S ACTIONS ARE THE SCREEN TABLE'S, hint included, so the row a reader reads and the chord the
 * keyboard answers to come from one place. Choosing a row has to actually navigate: a palette that lists the
 * screens and goes nowhere is the shape a mocked router would happily pass. */
async function openPalette(): Promise<void> {
  await renderSignedInAt("/week");
  await userEvent.keyboard("{Meta>}k{/Meta}");
  await userEvent.keyboard("{Control>}k{/Control}");
}

describe("the shell's command palette", () => {
  it("offers one action per screen, each with the chord that reaches it", async () => {
    await openPalette();

    for (const screenEntry of SCREENS) {
      expect(screen.getByText(`Go to ${screenEntry.label}`)).toBeInTheDocument();
      expect(screen.getByText(`g ${screenEntry.chord}`)).toBeInTheDocument();
    }
  });

  it("marks the screen the reader is on as the current row", async () => {
    await openPalette();

    const current = screen.getByText("Go to week").closest("[data-current]");
    expect(current).not.toBeNull();
  });

  it("navigates to the chosen screen, which is the whole of what it does today", async () => {
    await openPalette();

    await userEvent.click(screen.getByText("Go to backlog"));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Backlog");
  });
});

describe("SidebarNav", () => {
  it("renders one link per screen", async () => {
    const nav = await renderSignedInAt("/week");
    expect(nav.querySelectorAll("a")).toHaveLength(SCREENS.length);
  });

  it("renders a real link, so middle-click and cmd-click still work", async () => {
    await renderSignedInAt("/week");
    expect(screen.getByRole("link", { name: "backlog" })).toHaveAttribute("href", "/backlog");
  });

  it("marks the current item for styling and for assistive technology from one boolean", async () => {
    await renderSignedInAt("/areas");
    const current = screen.getByRole("link", { name: "areas" });
    expect(current).toHaveAttribute("data-current");
    expect(current).toHaveAttribute("aria-current", "page");
  });

  it("marks exactly one item as current", async () => {
    const nav = await renderSignedInAt("/learned");
    expect(nav.querySelectorAll("[data-current]")).toHaveLength(1);
  });

  it("leaves every other item unmarked", async () => {
    await renderSignedInAt("/areas");
    expect(screen.getByRole("link", { name: "week" })).not.toHaveAttribute("data-current");
  });

  it("is paper and not ink", async () => {
    const nav = await renderSignedInAt("/week");
    const fill = [...nav.classList].find((name) => name.startsWith("bg-"));
    if (fill === undefined) throw new Error("the sidebar declares no fill");

    const declarations = declarationsOf(await compileUtilities([fill]), fill);

    expect(declarations).toMatch(/var\(--paper(-raised)?\)/);
    expect(declarations).not.toMatch(/var\(--ink/);
  });
});

function renderNav(counts?: Record<string, number>) {
  return render(
    <MemoryRouter>
      <SidebarNav screens={SCREENS} currentPath="/week" counts={counts} />
    </MemoryRouter>,
  );
}

describe("the count at the right edge", () => {
  it("renders a count for a screen that has one to report", () => {
    renderNav({ "/backlog": 12 });
    expect(screen.getByRole("link", { name: /backlog/ })).toHaveTextContent(/^backlog12$/);
  });

  it("renders nothing for a screen with nothing to count", () => {
    renderNav({ "/backlog": 12 });
    expect(screen.getByRole("link", { name: "week" })).toHaveTextContent(/^week$/);
  });

  it("renders no count at all when none is supplied", () => {
    renderNav();
    expect(screen.getByRole("link", { name: "backlog" })).toHaveTextContent(/^backlog$/);
  });
});

/* THE CURRENT ITEM'S CHANNEL, which is the criterion's own subject: a wash fill plus a 3px --ink-deep left
 * rule, the same channel a selected block uses.
 *
 * Asserted against the stylesheet rather than against the rendered element, because the rule lives in a plain
 * co-located stylesheet that jsdom never applies: `getComputedStyle` on the link would report nothing and an
 * assertion over it would pass on a deleted rule. The token INDIRECTION is what is worth pinning, so the rule
 * must reach --state-hover and --state-selected-*, and those must separately resolve to the values the
 * criterion names.
 *
 * THE RULE MOVED TO `ui/primitives/states.css` IN TICKET 8, and the assertions moved with it. It was declared
 * here while the sidebar was the only row-shaped surface in the kit; a select item and a command-palette row
 * need the same three declarations, and the channel assertion refuses a second file assigning a state's
 * channel. So the sidebar row now takes the shared `state-row` class, which is what these tests check first:
 * a rule that exists in a file nothing imports would pass every assertion below and render nothing. */
describe("the current item's channel", () => {
  const statesCss = readFile(path.join(srcDir, "ui", "primitives", "states.css"), "utf8");
  const layoutCss = readFile(path.join(srcDir, "tokens", "layout.css"), "utf8");

  const currentRule = async (): Promise<string> => {
    const rule = /\.state-row\[data-current\]\s*\{([^}]*)\}/.exec(await statesCss);
    if (rule === null) throw new Error("states.css declares no [data-current] rule");
    return rule[1];
  };

  it("is the class the sidebar row actually carries", async () => {
    await renderSignedInAt("/week");
    const current = screen.getByRole("link", { name: /areas/ });

    expect(current.classList).toContain("state-row");
  });

  it("takes the fill from --state-hover rather than restating a wash", async () => {
    expect(await currentRule()).toMatch(/background-color:\s*var\(--state-hover\)/);
  });

  it("takes a left rule from --state-selected-color rather than restating --ink-deep", async () => {
    expect(await currentRule()).toMatch(/border-left-color:\s*var\(--state-selected-color\)/);
  });

  it("reserves the rule's width at rest, so becoming current changes no geometry", async () => {
    const atRest = /\.state-row\s*\{([^}]*)\}/.exec(await statesCss);
    expect(atRest?.[1]).toMatch(
      /border-left:\s*var\(--state-selected-border\)\s+solid\s+transparent/,
    );
  });

  it("resolves those tokens to the wash, the 3px and the ink the criterion names", async () => {
    const layout = await layoutCss;

    expect(layout).toMatch(/--state-hover:\s*var\(--ink-wash\)/);
    expect(layout).toMatch(/--state-selected-border:\s*3px/);
    expect(layout).toMatch(/--state-selected-color:\s*var\(--ink-deep\)/);
  });

  it("names no raw value of its own, so the channel cannot drift from the block's", async () => {
    const rule = await currentRule();

    expect(rule).not.toMatch(/#[0-9a-f]{3,6}/i);
    expect(rule).not.toMatch(/\b3px\b/);
  });
});
