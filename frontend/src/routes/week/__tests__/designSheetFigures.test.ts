/* THE WEEK MOCK'S PENDING-PROPOSAL COUNT, CROSSED AGAINST THE FIXTURE IT DRAWS.
 *
 * `docs/design/screens.html` renders the Week screen at rest, in weekly-session mode and in conflict, and its band
 * prints how many proposals are pending. `WeekViewResponse.proposal` is ONE optional object, and a later proposal
 * supersedes the one before it, so the api answers with nought or one: a mock that prints two describes a response no
 * client can receive, and a reader implementing from it meets a quantity that does not exist.
 *
 * THE SHEET IS RUN, NOT READ. It is one file whose inline script assembles every view from one fixture, so a printed
 * figure exists only once the script has run. The sheet's markup is installed in this environment's document and its
 * script is evaluated against it: `innerHTML` never executes a script, so the one evaluation here is the only one.
 * Nothing is fetched, so the linked token sheets are absent and the grid geometry resolves to NaN. No figure read here
 * is a measured pixel; every one is interpolated text.
 *
 * THE LAST TEST IS THE MUTATION. A count hard-coded at nought satisfies every case above it, so the fixture is given
 * two proposal targets and the printed figures must follow AND stay at one. A figure that cannot move is decoration,
 * and a figure that counts targets is the same defect in a second spelling.
 *
 * THE APPROVE CONTROL IS READ AS WELL AS THE FIGURES. `WeekActions` disables it on an empty slot and nothing else, so a
 * band drawing an enabled approve beside a count of nought depicts a state the product cannot produce. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { designSheetDir } from "../../../../scripts/lib/paths.ts";

/** The three views that are the Week screen, by the switcher's own view id. */
const WEEK_VIEWS = ["v-week", "v-session", "v-conflict"] as const;

/** Any figure that counts proposals, wherever a view prints one. */
const PROPOSAL_FIGURE = /(\d+) proposals?\b/g;

async function sheetText(): Promise<string> {
  return readFile(path.join(designSheetDir, "screens.html"), "utf8");
}

/** The fixture the grid draws, sliced out of the sheet's text so every reading below crosses the same source. */
function fixtureOf(sheet: string): string {
  const opening = sheet.indexOf("const WEEK = [");
  expect(opening, "the sheet no longer holds a `const WEEK` fixture").toBeGreaterThan(0);
  return sheet.slice(opening, sheet.indexOf("\n];", opening));
}

/** The fixture's proposal targets, read by a route the sheet itself does not use. */
function proposalTargetsIn(sheet: string): readonly string[] {
  return [...fixtureOf(sheet).matchAll(/'(\d\d:\d\d-\d\d:\d\d\|[^']*)'/g)]
    .map((match) => match[1])
    .filter((row) => (row.split("|")[3] ?? "").includes("?"));
}

/** The fixture's unconfirmed days, counted from the marker each one carries. */
function unconfirmedDaysIn(sheet: string): number {
  const marked = [...fixtureOf(sheet).matchAll(/\bunconf:\s*(?:true|[1-9])/g)];
  expect(marked.length, "the fixture no longer marks an unconfirmed day").toBeGreaterThan(0);
  return marked.length;
}

interface Rendered {
  /** What each Week view prints, keyed by view id. */
  readonly views: ReadonlyMap<string, string>;
  /** Whether each Week view's approve controls are disabled, in the order the view draws them. */
  readonly approveDisabled: ReadonlyMap<string, readonly boolean[]>;
  /** The count on the sidebar's own "This week · Proposals" row, which every view is rendered beside. */
  readonly sidebarProposals: string | undefined;
}

function render(sheet: string): Rendered {
  const parsed = new DOMParser().parseFromString(sheet, "text/html");
  document.documentElement.innerHTML = parsed.documentElement.innerHTML;
  const script = [...parsed.querySelectorAll("script")]
    .map((element) => element.textContent)
    .join("\n");
  expect(script, "the sheet no longer carries its own script").not.toBe("");
  new Function(script)();

  const views = new Map<string, string>();
  const approveDisabled = new Map<string, readonly boolean[]>();
  for (const view of WEEK_VIEWS) {
    const button = document.querySelector(`.doc button[data-v="${view}"]`);
    expect(button, `the sheet no longer renders ${view}`).not.toBeNull();
    (button as HTMLButtonElement).click();
    views.set(view, document.querySelector("#main")?.textContent ?? "");
    approveDisabled.set(
      view,
      [...document.querySelectorAll<HTMLButtonElement>("#main button")]
        .filter((control) => control.textContent?.startsWith("Approve") === true)
        .map((control) => control.disabled),
    );
  }

  const rows = [...document.querySelectorAll(".side nav a")];
  const proposals = rows.find((row) => row.textContent?.startsWith("Proposals"));
  return {
    views,
    approveDisabled,
    sidebarProposals: proposals?.querySelector("b")?.textContent ?? undefined,
  };
}

function figuresIn(text: string): readonly number[] {
  return [...text.matchAll(PROPOSAL_FIGURE)].map((match) => Number(match[1]));
}

describe("the pending-proposal count the Week mock prints", () => {
  it("names a quantity the response can carry, in every Week view and in the sidebar", async () => {
    const { views, sidebarProposals } = render(await sheetText());

    for (const [view, text] of views) {
      for (const figure of figuresIn(text)) {
        expect(figure, `${view} prints ${figure} proposals`).toBeLessThanOrEqual(1);
      }
    }
    expect(
      Number(sidebarProposals),
      "the sidebar counts this week's proposals",
    ).toBeLessThanOrEqual(1);
  });

  /* THE SIDEBAR AND THE BAND READ ONE WEEK. Two statements of one quantity is how the mock came to print a count the
   * api cannot answer with: one was updated and the other was not. */
  it("collapses the fixture's proposal targets the way the slot does, everywhere it prints them", async () => {
    const sheet = await sheetText();
    const expected = proposalTargetsIn(sheet).length === 0 ? 0 : 1;
    const { views, sidebarProposals } = render(sheet);

    expect(figuresIn(views.get("v-week") ?? "")).toEqual([expected]);
    expect(figuresIn(views.get("v-conflict") ?? "")).toEqual([expected]);
    expect(sidebarProposals).toBe(String(expected));
  });

  /* THE OTHER FIGURE ON THAT LINE IS DERIVED TOO, so it is pinned to the same fixture. It happened to be right when the
   * proposal count beside it was wrong, which is what an unpinned derivation buys. */
  it("counts the unconfirmed days the fixture marks", async () => {
    const sheet = await sheetText();
    const { views } = render(sheet);

    expect(views.get("v-week")).toContain(`${unconfirmedDaysIn(sheet)} days unconfirmed`);
  });

  /* APPROVE IS DISABLED BY AN EMPTY SLOT AND BY NOTHING ELSE, which `WeekActions` derives from the same field. The
   * conflict view offers no approve at all: it answers with `Resolve`, and an empty list here says so. */
  it("draws the approve control the way the slot leaves it", async () => {
    const sheet = await sheetText();
    const empty = proposalTargetsIn(sheet).length === 0;
    const { approveDisabled } = render(sheet);

    expect(approveDisabled.get("v-week")).toEqual([empty]);
    expect(approveDisabled.get("v-session")).toEqual([empty]);
    expect(approveDisabled.get("v-conflict")).toEqual([]);
  });

  it("keeps the band's second line two figures", async () => {
    const { views } = render(await sheetText());

    expect(views.get("v-week")).toMatch(/\d+ proposals? pending · \d+ days? unconfirmed/);
  });

  it("collapses two planted targets to the one slot the response carries", async () => {
    let planted = 0;
    const flagged = (await sheetText()).replace(/\|([A-Za-z]+)'/g, (whole, area: string) =>
      (planted += 1) <= 2 ? `|${area}?'` : whole,
    );
    expect(
      proposalTargetsIn(flagged),
      "the fixture's rows no longer end in an Area field",
    ).toHaveLength(2);

    const { views, approveDisabled, sidebarProposals } = render(flagged);

    expect(views.get("v-week")).toContain("1 proposal pending");
    expect(views.get("v-conflict")).toContain("1 proposal waiting quietly");
    expect(sidebarProposals).toBe("1");
    expect(approveDisabled.get("v-week")).toEqual([false]);
    expect(approveDisabled.get("v-session")).toEqual([false]);
  });
});
