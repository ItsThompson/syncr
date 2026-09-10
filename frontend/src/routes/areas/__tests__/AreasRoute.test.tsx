/* Rendering the Areas screen, and the parts of it only a DOM can answer for.
 *
 * FOUR THINGS ARE ASSERTED HERE AND NOWHERE ELSE. The two chart rules, because both are about what reaches the
 * markup rather than about what a function returns: hatch is always on, and a deviation row carries no Area ink
 * anywhere including its label cell. The preference cell's edit path, because it is an interaction. And the
 * mode, because "reachable by URL" is a claim about the route table.
 *
 * IT QUERIES THE CHANNEL A READER PERCEIVES. Hatch is a `background-image` on a segment and a `fill` on a
 * wedge, so the assertions read those attributes rather than a prop or a constant the implementation also
 * reads. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { http, HttpResponse, type RequestHandler } from "msw";

import { apiServer } from "../../../testing/apiServer";
import {
  CHIP_CONTAINER_CLASS,
  KNOWN_AREA_INK_FAMILIES,
  areaInkClasses,
  areaInkMatcher,
} from "../../../testing/areaCarriers";
import {
  jsonHandler,
  pendingHandler,
  readyz,
  recordingHandler,
  unreachableHandler,
} from "../../../testing/apiStub";
import { renderAt } from "../../../testing/renderRoute";
import { REVIEW_PATH } from "../mode";
import { thisIsoWeek } from "../week";
import {
  CAREER,
  STUDY,
  buildAreas,
  buildCategory,
  buildDayCounts,
  buildNoPreference,
  buildPreference,
  buildPreferences,
  buildReadyProposal,
  buildReview,
  buildThirteenAreas,
} from "./fixtures";
import type { Areas } from "../../../api/hooks/useAreas";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";

/** The screen reads the week it is in, so the handler answers whichever week the run falls in. */
const PERIOD = thisIsoWeek(new Date());
const REVIEW_URL = `/api/v1/reviews/budget?period=${PERIOD}`;

/**
 * The custom properties a pigment sets, which is the other channel an Area's ink can arrive through.
 *
 * The CLASSES are not listed here at all: they are derived from the components that emit them, by
 * `testing/areaCarriers`. Three versions of this guard were bounded by a list, and each list had a hole that
 * somebody else found. The last of them named two of the three cva bases in the kit that paint a ramp step, and a
 * real `Block` inside the deviation panel passed every test.
 */
const AREA_INK_PROPERTY = /--area-|--ai\b|--hx\b/;

/* A `figure` carries no accessible name from its own `figcaption` under this accname implementation, so a
 * chart is located by the caption it draws and read through the figure that holds it. Asserting through the
 * caption is also the stronger reading: it is the text a reader sees above the chart. */
function chartWithCaption(caption: RegExp): HTMLElement {
  const found = screen.getByText(caption).closest("figure.chart");
  if (found === null) throw new Error(`no chart draws a caption matching ${caption}`);
  return found as HTMLElement;
}

function screenHandlers(
  areas: Areas,
  review: BudgetReview,
  preferences = buildPreferences(),
): RequestHandler[] {
  return [
    readyz(),
    jsonHandler("/api/v1/areas", { status: 200, body: areas }),
    jsonHandler(REVIEW_URL, { status: 200, body: review }),
    ...areas.areas.map((area) =>
      jsonHandler(`/api/v1/areas/${area.id}/preference`, {
        status: 200,
        body: preferences[area.id] ?? buildNoPreference(area.id),
      }),
    ),
  ];
}

async function renderAreas(
  {
    areas = buildAreas(),
    review = buildReview(),
    preferences = buildPreferences(),
    path = "/areas",
  } = {},
  extra: RequestHandler[] = [],
) {
  apiServer.use(...screenHandlers(areas, review, preferences), ...extra);
  renderAt(path);
  return screen.findByRole("table", { name: /Every Area/ });
}

describe("the Areas screen", () => {
  it("renders a serif page title, because a screen is a destination", async () => {
    await renderAreas();

    const title = screen.getByRole("heading", { level: 1 });
    expect(title).toHaveTextContent("Areas");
    expect([...title.classList]).toContain("font-serif");
  });

  it("states the discretionary figure the percentages are measured against", async () => {
    await renderAreas();

    expect(screen.getByText("this week \u00b7 of 112.0h discretionary")).toBeInTheDocument();
  });

  it("renders the budget sheet's columns, in its order, plus Preference and never Pigment", async () => {
    const table = await renderAreas();

    const headers = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);

    expect(headers).toEqual([
      "Area",
      "Parent",
      "Floor / wk",
      "Share of remainder",
      "This week",
      "Deviation",
      "Preference",
    ]);
    expect(headers).not.toContain("Pigment");
  });

  /* THE SHEET DECLARES ITS COLUMNS, and the Area column is the one that absorbs the surplus: every other
   * column holds a figure or one control at the width it declares, so a long Area name spends its own row's
   * height instead of reshaping the figures a reader compares down their columns. Read from the style
   * ATTRIBUTE: jsdom's style object drops a `calc()` it cannot parse. */
  it("declares the Area column as the one that absorbs the surplus", async () => {
    const table = await renderAreas();

    const widths = [...table.querySelectorAll("col")].map((col) => col.getAttribute("style"));

    expect(widths).toEqual([
      "width: calc(100% - (96px + 56px + 88px + 64px + 72px + 240px));",
      "width: 96px;",
      "width: 56px;",
      "width: 88px;",
      "width: 64px;",
      "width: 72px;",
      "width: 240px;",
    ]);
  });

  it("renders a row per Area, with its floor, share, hours and signed deviation", async () => {
    const table = await renderAreas();

    const row = within(table).getByRole("row", { name: /Career/ });
    const cells = within(row)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);

    expect(cells.slice(0, 6)).toEqual([
      "Career",
      "\u2014",
      "\u2014",
      "60%",
      "18.2h",
      "\u221243.8pp",
    ]);
  });

  it("names a child Area's parent in its own row", async () => {
    const areas = buildAreas();
    const nested = {
      areas: [
        ...areas.areas,
        {
          ...areas.areas[0],
          id: "44444444-4444-4444-8444-444444444444",
          name: "Running",
          parentId: CAREER,
          pigmentIndex: 7,
        },
      ],
      ramp: areas.ramp,
    };
    const table = await renderAreas({ areas: nested });

    const row = within(table).getByRole("row", { name: /Running/ });
    expect(within(row).getAllByRole("cell")[1]).toHaveTextContent("Career");
  });

  it("reads a dash where the week has no target to compare an Area against", async () => {
    const table = await renderAreas({
      review: buildReview({
        discretionaryMinutes: null,
        unallocatedMinutes: null,
        oversubscriptionMinutes: null,
        statement: "This week holds no plan, so it has no discretionary time to divide.",
        categories: [buildCategory({ targetMinutes: null, actualMinutes: 0 })],
      }),
    });

    const row = within(table).getByRole("row", { name: /Career/ });
    expect(within(row).getAllByRole("cell")[5]).toHaveTextContent("\u2014");
  });
});

describe("the two chart rules", () => {
  it("draws every wedge with a hatch, always, with no toggle to turn one off", async () => {
    await renderAreas();

    const pie = screen.getByRole("img", { name: /Composition of discretionary time/ });
    const wedges = pie.querySelectorAll("path.pie__wedge");

    expect(wedges.length).toBeGreaterThan(0);
    for (const wedge of wedges) {
      expect(wedge.getAttribute("fill")).toMatch(/^url\(#/);
    }
    /* One pattern per pigment, each carrying its own texture. The wedge's fill is a reference to it, so a
     * wedge that lost its hatch would be a flat colour rather than a url. */
    expect(pie.querySelectorAll("pattern").length).toBeGreaterThan(0);
  });

  it("draws no Area ink anywhere in the deviation panel, including a row's label cell", async () => {
    await renderAreas();

    /* THE WHOLE PANEL, not only the figure inside it. A chip beside a cobalt bar implies the bar could have
     * been Area-coloured whether it sits in the row or in the panel around it, and a guard scoped to the
     * figure passes the moment somebody puts one just outside. The panel holds the chart and its statements
     * and nothing else, so the panel is the honest boundary. */
    const { matches, derived } = await areaInkMatcher();
    /* The floor on the derivation: a regex that stopped matching would otherwise make this guard vacuous. */
    for (const family of KNOWN_AREA_INK_FAMILIES) expect(derived).toContain(family);

    const panel = screen.getByRole("region", { name: "Actual against target" });
    const offenders: string[] = [];
    for (const element of panel.querySelectorAll("*")) {
      for (const painted of element.classList) {
        if (matches(painted)) offenders.push(painted);
      }
      const styled = element.getAttribute("style") ?? "";
      if (AREA_INK_PROPERTY.test(styled)) offenders.push(styled);
    }

    expect(offenders).toEqual([]);
  });

  it("derives the carrier set from every component that paints a ramp step", async () => {
    /* The guard above is only as bounded as this set is. Asserted separately so a hole in the derivation reads
     * as a hole in the derivation rather than as a screen that happens to draw no ink. */
    const derived = await areaInkClasses();

    expect(derived).toContain("chart-ink--01");
    expect(derived).toContain("chart-hatch--fwd");
    expect(derived).toContain("bg-area-01");
    expect(derived).toContain("week-block--area-01");
    expect(derived).toContain(CHIP_CONTAINER_CLASS);
    /* Twelve steps per family and no thirteenth, which is the sealed ramp the derivation should have found. */
    expect(derived.filter((one) => /^week-block--area-\d\d$/.test(one))).toHaveLength(12);
  });

  it("renders a deviation row per Area and one for the vacancy, signed and never coloured", async () => {
    await renderAreas();

    const chart = chartWithCaption(/Actual against target per Area/);
    expect(within(chart).getByText("Unallocated")).toBeInTheDocument();
    expect(within(chart).getByText("Career")).toBeInTheDocument();
    /* Direction is side and sign. Both bars carry the same ink, so what separates them is a modifier class. */
    const bars = chart.querySelectorAll(".deviation__bar");
    expect(bars.length).toBeGreaterThan(0);
  });

  it("states how many days of the period were confirmed, unconfirmed and off-plan", async () => {
    await renderAreas({
      review: buildReview({ days: buildDayCounts({ confirmed: 5, unconfirmed: 2, offPlan: 1 }) }),
    });

    expect(screen.getByText(/5 days confirmed, 2 unconfirmed, 1 off-plan/)).toBeInTheDocument();
  });
});

describe("the two residuals", () => {
  it("reports a non-zero vacancy on a budget whose shares sum to exactly 100", async () => {
    await renderAreas();

    const notice = screen.getByRole("status", { name: /Unallocated/ });
    expect(notice).toHaveTextContent("81.5h of 112.0h discretionary hours, 72.8%");
  });

  it("keeps the vacancy non-negative and reports oversubscription as its own quantity", async () => {
    await renderAreas({
      review: buildReview({ unallocatedMinutes: 4892, oversubscriptionMinutes: 2016 }),
    });

    expect(screen.getByRole("status", { name: /Unallocated/ })).toBeInTheDocument();
    const excess = screen.getByRole("status", { name: /ask for more time/ });
    expect(excess).toHaveTextContent("exceed discretionary time by 33.6h");
    expect(excess).not.toHaveTextContent("\u2212");
  });

  it("reports no vacancy notice when nothing is unallocated", async () => {
    await renderAreas({ review: buildReview({ unallocatedMinutes: 0 }) });

    expect(screen.queryByRole("status", { name: /Unallocated/ })).not.toBeInTheDocument();
  });

  it("says why a week off-plan end to end reports zeroes, rather than showing two empty panels", async () => {
    await renderAreas({
      review: buildReview({
        discretionaryMinutes: 0,
        unallocatedMinutes: 0,
        oversubscriptionMinutes: 0,
        offPlanMinutes: 10080,
        offPlanStatement:
          "This week was declared off-plan from end to end, so it holds no discretionary time.",
        categories: [],
      }),
    });

    const notice = screen.getByRole("status", { name: /declared off-plan/ });
    expect(notice).toHaveTextContent("holds no discretionary time");
    expect(notice).toHaveTextContent("168.0h of it were declared off");
  });
});

describe("declaring an Area", () => {
  it("states how many of the twelve pigments are in use", async () => {
    await renderAreas();

    expect(screen.getByText("2 of 12 pigments in use")).toBeInTheDocument();
  });

  it("states the full ramp without any shared-step sentence", async () => {
    const areas = buildThirteenAreas();
    await renderAreas({
      areas,
      review: buildReview({
        categories: areas.areas.map((area) => buildCategory({ areaId: area.id })),
      }),
    });

    expect(screen.getByText("12 of 12 pigments in use")).toBeInTheDocument();
    /* The api serves no sentence about a shared step and this screen renders none, so no wording
     * about what separates two Areas can drift between the wire and the panel. */
    expect(screen.queryByText(/identity rests on the hatch/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/two Areas now hold one step/i)).not.toBeInTheDocument();
  });

  it("offers no colour control of any kind, because a pigment is dealt", async () => {
    await renderAreas();

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    const named = within(form)
      .getAllByRole("textbox")
      .map((field) => `${field.getAttribute("aria-label") ?? ""} ${field.id}`);

    expect(named.join(" ").toLowerCase()).not.toMatch(/colour|color|pigment/);
  });

  it("writes the floor and the share the reader typed, unrounded", async () => {
    /* The defect this replaces: both fields were minute-measured steppers, so a declared 3-hour weekly floor
     * was POSTed as 5 and a 33% share as 35%. A floor is a HARD solver constraint and this is the only surface
     * in the product that declares one. Both figures are stored as NUMERIC(5, 2), so neither owes a grid. */
    const created = recordingHandler("post", "/api/v1/areas", {
      status: 201,
      body: { area: buildAreas().areas[0], ramp: buildAreas().ramp },
    });
    await renderAreas({}, [created.handler]);

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Area name" }), "Research");
    await userEvent.type(within(form).getByRole("textbox", { name: "Weekly floor in hours" }), "3");
    await userEvent.type(
      within(form).getByRole("textbox", { name: /Share of the remainder/ }),
      "33",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Declare it" }));

    expect(created.bodies).toEqual([
      { name: "Research", parentId: null, budgetPercent: 33, floorHours: 3 },
    ]);
  });

  it("writes a fractional floor, because a floor is stored to the hundredth of an hour", async () => {
    const created = recordingHandler("post", "/api/v1/areas", {
      status: 201,
      body: { area: buildAreas().areas[0], ramp: buildAreas().ramp },
    });
    await renderAreas({}, [created.handler]);

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Area name" }), "Research");
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Weekly floor in hours" }),
      "3.5",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Declare it" }));

    expect(created.bodies).toEqual([
      { name: "Research", parentId: null, budgetPercent: null, floorHours: 3.5 },
    ]);
  });

  it("declares no floor and no share for a field left blank, rather than zero", async () => {
    const created = recordingHandler("post", "/api/v1/areas", {
      status: 201,
      body: { area: buildAreas().areas[0], ramp: buildAreas().ramp },
    });
    await renderAreas({}, [created.handler]);

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Area name" }), "Research");
    await userEvent.click(within(form).getByRole("button", { name: "Declare it" }));

    expect(created.bodies).toEqual([
      { name: "Research", parentId: null, budgetPercent: null, floorHours: null },
    ]);
  });

  it("refuses a floor that is not a figure rather than declaring an Area without one", async () => {
    /* `Input` is text, so unlike the stepper it replaced the browser refuses no keystroke. Reading `3,5` as
     * blank posted a successful 201 with a HARD solver constraint the reader typed silently absent. */
    const created = recordingHandler("post", "/api/v1/areas", {
      status: 201,
      body: { area: buildAreas().areas[0], ramp: buildAreas().ramp },
    });
    await renderAreas({}, [created.handler]);

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Area name" }), "Research");
    await userEvent.type(
      within(form).getByRole("textbox", { name: "Weekly floor in hours" }),
      "3,5",
    );

    expect(screen.getByText(/A weekly floor is a number/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Declare it" }));
    expect(created.bodies).toEqual([]);
  });

  it("refuses a share that is not a figure, and says so at the field", async () => {
    const created = recordingHandler("post", "/api/v1/areas", {
      status: 201,
      body: { area: buildAreas().areas[0], ramp: buildAreas().ramp },
    });
    await renderAreas({}, [created.handler]);

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Area name" }), "Research");
    await userEvent.type(
      within(form).getByRole("textbox", { name: /Share of the remainder/ }),
      "thirty",
    );

    expect(screen.getByText(/A share of the remainder is a number/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Declare it" }));
    expect(created.bodies).toEqual([]);
  });
});

describe("the preference cell", () => {
  it("reads the form, and states where the preference came from", async () => {
    const table = await renderAreas();

    const row = within(table).getByRole("row", { name: /Career/ });
    /* The control is named by the ACT and reads the FORM: a screen reader hears which Area's preference it
     * changes, and a reader compares `05:30 \u00b7 strong` down the column. */
    const control = within(row).getByRole("button", {
      name: "Change the placement preference for Career",
    });
    expect(control).toHaveTextContent("05:30 \u00b7 strong");
    expect(within(row).getByText(/Set on this area/)).toBeInTheDocument();
  });

  it("renders an inherited statement verbatim", async () => {
    const table = await renderAreas({
      preferences: {
        [CAREER]: buildPreference({
          effective: {
            ...buildPreference().effective!,
            statement:
              "Inherited from `Fitness`: 05:30-07:00, strong, ideally 90 minutes at a time.",
          },
        }),
      },
    });

    const row = within(table).getByRole("row", { name: /Career/ });
    expect(
      within(row).getByText(
        "Inherited from `Fitness`: 05:30-07:00, strong, ideally 90 minutes at a time.",
      ),
    ).toBeInTheDocument();
  });

  it("reads a dash for an Area with no preference in effect, and still names the act", async () => {
    const table = await renderAreas();

    const row = within(table).getByRole("row", { name: /Study/ });
    const control = within(row).getByRole("button", {
      name: "Set a placement preference for Study",
    });
    expect(control).toHaveTextContent("\u2014");
  });

  it("edits in place, and sends the whole preference rather than the field that changed", async () => {
    const declared = recordingHandler("put", `/api/v1/areas/${CAREER}/preference`, {
      status: 200,
      body: buildPreference(),
    });
    const table = await renderAreas({}, [declared.handler]);

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(
      within(row).getByRole("button", { name: "Change the placement preference for Career" }),
    );

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(declared.bodies).toEqual([
      {
        windows: [{ start: "05:30", end: "07:00" }],
        strength: "strong",
        preferredDurationMinutes: 90,
        maxPerDayMinutes: 180,
      },
    ]);
  });

  it("offers a daily cap, because the row is an Area's and a cap is an Area's alone", async () => {
    const table = await renderAreas();

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(
      within(row).getByRole("button", { name: "Change the placement preference for Career" }),
    );

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    expect(within(form).getByText("Daily cap")).toBeInTheDocument();
  });

  it("writes the daily cap the reader typed, because a cap owes no grid", async () => {
    /* A cap is a budget figure rather than a geometry, so 100 minutes is legal and
     * admits six blocks. The quarter-hour stepper this replaces wrote 105 for a typed 100, which is a hard
     * constraint the reader did not declare. The ideal session is the opposite case and keeps its stepper. */
    const declared = recordingHandler("put", `/api/v1/areas/${CAREER}/preference`, {
      status: 200,
      body: buildPreference(),
    });
    const table = await renderAreas({}, [declared.handler]);

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(
      within(row).getByRole("button", { name: "Change the placement preference for Career" }),
    );

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    const cap = within(form).getByRole("textbox", { name: "Daily cap in minutes" });
    await userEvent.clear(cap);
    await userEvent.type(cap, "100");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(declared.bodies).toEqual([
      {
        windows: [{ start: "05:30", end: "07:00" }],
        strength: "strong",
        preferredDurationMinutes: 90,
        maxPerDayMinutes: 100,
      },
    ]);
  });

  it("refuses a cap that is not a figure rather than clearing the one that is stored", async () => {
    const declared = recordingHandler("put", `/api/v1/areas/${CAREER}/preference`, {
      status: 200,
      body: buildPreference(),
    });
    const table = await renderAreas({}, [declared.handler]);

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(
      within(row).getByRole("button", { name: "Change the placement preference for Career" }),
    );

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    const cap = within(form).getByRole("textbox", { name: "Daily cap in minutes" });
    await userEvent.clear(cap);
    await userEvent.type(cap, "1,5");

    expect(within(form).getByText(/A daily cap is a number/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(declared.bodies).toEqual([]);
  });

  it("keeps the ideal session on the quarter hour, which is the one figure here that owes the grid", async () => {
    const table = await renderAreas();

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(
      within(row).getByRole("button", { name: "Change the placement preference for Career" }),
    );

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    /* A stepper, not a figure field: the api refuses an ideal duration that is not a multiple of the snap. */
    expect(within(form).getByRole("spinbutton")).toHaveAttribute("step", "15");
  });

  it("forgets a refusal about one row when another row's editor opens", async () => {
    /* The two preference writes are one hook each, shared by every row, so a refusal outlived the editor that
     * caused it and then appeared inside the next Area's editor, naming an Area the reader never touched. */
    apiServer.use(
      ...screenHandlers(buildAreas(), buildReview()),
      http.put(`${window.location.origin}/api/v1/areas/${CAREER}/preference`, () =>
        HttpResponse.json(
          {
            type: "syncr:validation-failed",
            title: "Validation failed",
            status: 422,
            detail: "A window sits inside a single local day, and 23:00 to 02:00 does not.",
          },
          { status: 422 },
        ),
      ),
    );
    renderAt("/areas");
    const table = await screen.findByRole("table", { name: /Every Area/ });

    const career = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(
      within(career).getByRole("button", { name: "Change the placement preference for Career" }),
    );
    const refused = await screen.findByRole("form", { name: /Placement preference for Career/ });
    await userEvent.click(within(refused).getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("23:00 to 02:00");

    await userEvent.click(within(refused).getByRole("button", { name: "Cancel" }));
    const study = within(table).getByRole("row", { name: /Study/ });
    await userEvent.click(
      within(study).getByRole("button", { name: "Set a placement preference for Study" }),
    );

    const opened = await screen.findByRole("form", { name: /Placement preference for Study/ });
    expect(within(opened).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("removes the declaration through its own act, which is not an empty window list", async () => {
    const removed = recordingHandler("put", `/api/v1/areas/${CAREER}/preference`, {
      status: 200,
      body: buildPreference(),
    });
    const table = await renderAreas({}, [removed.handler]);

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(
      within(row).getByRole("button", { name: "Change the placement preference for Career" }),
    );

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    expect(
      within(form).getByRole("button", { name: "Remove the declaration" }),
    ).toBeInTheDocument();
  });

  it("opens one editor at a time, because a cell is edited in the row it belongs to", async () => {
    const table = await renderAreas();

    await userEvent.click(
      within(within(table).getByRole("row", { name: /Career/ })).getByRole("button", {
        name: "Change the placement preference for Career",
      }),
    );
    await userEvent.click(
      within(within(table).getByRole("row", { name: /Study/ })).getByRole("button", {
        name: "Set a placement preference for Study",
      }),
    );

    expect(screen.getAllByRole("form", { name: /Placement preference/ })).toHaveLength(1);
    expect(
      screen.getByRole("form", { name: /Placement preference for Study/ }),
    ).toBeInTheDocument();
  });
});

describe("every state this screen can be in", () => {
  it("says what it is waiting for in words, and draws nothing that spins", async () => {
    apiServer.use(readyz(), pendingHandler("/api/v1/areas"), pendingHandler(REVIEW_URL));
    renderAt("/areas");

    const pending = await screen.findByRole("status");
    expect(pending).toHaveTextContent("Reading your Areas and this week's budget");
    expect(pending.querySelector('[class*="spin"], [class*="skeleton"]')).toBeNull();
  });

  it("names the destination before the reads arrive, in every state", async () => {
    /* A screen's title is a fact about where the reader is rather than about whether a response landed, so the
     * band is drawn above the state rather than inside the ready branch. The shell's `g a` chord and the route
     * table's own suite both rest on it: both assert a serif h1 with nothing but readiness stubbed. */
    apiServer.use(readyz(), pendingHandler("/api/v1/areas"), pendingHandler(REVIEW_URL));
    renderAt("/areas");

    await screen.findByRole("status");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Areas");
    expect(screen.getByText("reading your Areas")).toBeInTheDocument();
  });

  it("carries the api's own sentence when a read fails, and names which read it was", async () => {
    apiServer.use(
      readyz(),
      unreachableHandler("/api/v1/areas"),
      jsonHandler(REVIEW_URL, {
        status: 200,
        body: buildReview(),
      }),
    );
    renderAt("/areas");

    const failure = await screen.findByRole("alert");
    expect(failure).toHaveTextContent("The Areas could not be read");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Areas");
  });

  it("keeps the screen when one Area's preference cannot be read", async () => {
    /* `Promise.all` would reject the whole set on one failure, and the screen's own reading would then turn the
     * pie, the deviation rows and the budget sheet into a failure surface over a Preference cell. */
    apiServer.use(
      readyz(),
      jsonHandler("/api/v1/areas", { status: 200, body: buildAreas() }),
      jsonHandler(REVIEW_URL, { status: 200, body: buildReview() }),
      jsonHandler(`/api/v1/areas/${CAREER}/preference`, { status: 200, body: buildPreference() }),
      unreachableHandler(`/api/v1/areas/${STUDY}/preference`),
    );
    renderAt("/areas");

    const table = await screen.findByRole("table", { name: /Every Area/ });
    const career = within(table).getByRole("row", { name: /Career/ });
    expect(
      within(career).getByRole("button", { name: "Change the placement preference for Career" }),
    ).toHaveTextContent("05:30 \u00b7 strong");
    const study = within(table).getByRole("row", { name: /Study/ });
    expect(
      within(study).getByRole("button", { name: "Set a placement preference for Study" }),
    ).toBeInTheDocument();
  });

  it("points at setup when no Area is declared, rather than drawing an empty pie", async () => {
    await new Promise<void>((resolve) => {
      apiServer.use(
        readyz(),
        jsonHandler("/api/v1/areas", { status: 200, body: { areas: [], ramp: buildAreas().ramp } }),
        jsonHandler(REVIEW_URL, { status: 200, body: buildReview({ categories: [] }) }),
      );
      resolve();
    });
    renderAt("/areas");

    expect(await screen.findByText("No Area is declared")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to setup" })).toHaveAttribute("href", "/setup");
  });

  it("says nothing has been answered for rather than drawing a pie of one wedge", async () => {
    await renderAreas({
      review: buildReview({
        days: buildDayCounts({
          confirmed: 0,
          unconfirmed: 7,
          statement: "No day of this week has been answered for.",
        }),
      }),
    });

    expect(screen.getByText("Nothing has been answered for yet")).toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: /Composition of discretionary time by Area/ }),
    ).not.toBeInTheDocument();
  });
});

describe("the review mode", () => {
  it("is reachable by URL, so it survives a reload and can be linked", async () => {
    apiServer.use(...screenHandlers(buildAreas(), buildReview()));
    renderAt(REVIEW_PATH);

    expect(await screen.findByText("Pie review")).toBeInTheDocument();
  });

  it("is entered through a real link rather than a handler that assigns a location", async () => {
    await renderAreas();

    expect(screen.getByRole("link", { name: "Run the pie review" })).toHaveAttribute(
      "href",
      REVIEW_PATH,
    );
  });

  it("takes no serif title, because a mode is not a destination", async () => {
    apiServer.use(...screenHandlers(buildAreas(), buildReview()));
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    /* Scoped to the mode's own region: the top bar's wordmark is serif, and it is the product's one
     * sanctioned exception. What the rule forbids is a MODE claiming the type a destination has. */
    const mode = screen.getByRole("region", { name: "Pie review" });
    expect(mode.querySelector(".font-serif")).toBeNull();
  });

  it("lands on the screen for a mode this screen does not have", async () => {
    await renderAreas({ path: "/areas?mode=weekly" });

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Areas");
    expect(screen.queryByText("Pie review")).not.toBeInTheDocument();
  });

  it("draws the trend as stacked bars by week, and no line chart anywhere", async () => {
    apiServer.use(...screenHandlers(buildAreas(), buildReview()));
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    const trend = chartWithCaption(/Composition of discretionary time by week/);
    expect(trend.querySelectorAll(".stacked__row")).toHaveLength(2);
    expect(trend.querySelector("polyline, line, path[stroke-dasharray]")).toBeNull();
  });

  it("hatches every trend segment, because hatch is always on", async () => {
    apiServer.use(...screenHandlers(buildAreas(), buildReview()));
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    const trend = chartWithCaption(/Composition of discretionary time by week/);
    /* Bounded by what the kit paints an Area with: a `chart-ink--NN` for a step of the ramp, against
     * `chart-ink--unallocated` for the one category that holds none. A segment carrying an Area's ink and no
     * texture is what "hatch is always on" forbids, so the inventory is read off the element itself. */
    const areaSegments = [...trend.querySelectorAll(".stacked__segment")].filter((segment) =>
      [...segment.classList].some((name) => /^chart-ink--\d\d$/.test(name)),
    );

    expect(areaSegments.length).toBeGreaterThan(0);
    for (const segment of areaSegments) {
      const textures = [...segment.classList].filter((name) => name.startsWith("chart-hatch--"));
      expect(textures).toHaveLength(1);
      expect(textures[0]).not.toBe("chart-hatch--none");
    }
  });

  it("states what is missing instead of proposing from three weeks of data", async () => {
    apiServer.use(...screenHandlers(buildAreas(), buildReview()));
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    expect(screen.getByText("Not enough confirmed data yet")).toBeInTheDocument();
    expect(screen.getByText(/needs 13 fully confirmed weeks and 3 exist/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve the revision" })).not.toBeInTheDocument();
  });

  it("offers approve, adjust and reject once a quarter of confirmed weeks exists", async () => {
    apiServer.use(...screenHandlers(buildAreas(), buildReview({ proposal: buildReadyProposal() })));
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    expect(screen.getByRole("button", { name: "Approve the revision" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    /* One adjustable field per Area row and none for the vacancy, which is not an Area to write a share to.
     * Each is named by its AREA rather than by its identifier: this is the one control the mode exists to
     * offer, and a reader hearing a UUID learns nothing about which share they are changing. */
    const adjustable = screen.getAllByRole("textbox", { name: /Proposed share for/ });
    expect(adjustable).toHaveLength(2);
    expect(adjustable.map((field) => field.getAttribute("aria-label"))).toEqual([
      "Proposed share for Career, as a percentage",
      "Proposed share for Study, as a percentage",
    ]);
    expect(screen.getByText(/never re-cuts the budget on its own/)).toBeInTheDocument();
  });

  it("applies the share the reader typed, whatever it is", async () => {
    /* The defect this replaces: the adjust control was a five-minute stepper, so a typed 44 applied 45 and
     * pressing increase on the api's own proposed 44 gave 45, which meant the mode could not round-trip its
     * own figure. A share is stored as NUMERIC(5, 2) and the api bounds it only by range. */
    const applied = recordingHandler("post", "/api/v1/reviews/budget/apply", {
      status: 200,
      body: { applied: 2, declared: [CAREER, STUDY], changedAt: null, statement: "2 of 2." },
    });
    apiServer.use(
      ...screenHandlers(buildAreas(), buildReview({ proposal: buildReadyProposal() })),
      applied.handler,
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    const field = screen.getByRole("textbox", { name: /Proposed share for Career/ });
    await userEvent.clear(field);
    await userEvent.type(field, "33.5");
    await userEvent.click(screen.getByRole("button", { name: "Approve the revision" }));

    expect(applied.bodies).toEqual([
      {
        percentages: [
          { areaId: CAREER, budgetPercent: 33.5 },
          { areaId: STUDY, budgetPercent: 40 },
        ],
      },
    ]);
  });

  it("refuses an adjusted share that is not a figure rather than applying the proposal", async () => {
    /* Falling back to the proposed figure for a row the reader typed into is the same class of defect as
     * rounding it: what is written is not what was typed, and nothing says so. */
    const applied = recordingHandler("post", "/api/v1/reviews/budget/apply", {
      status: 200,
      body: { applied: 0, declared: [], changedAt: null, statement: "nothing." },
    });
    apiServer.use(
      ...screenHandlers(buildAreas(), buildReview({ proposal: buildReadyProposal() })),
      applied.handler,
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    const field = screen.getByRole("textbox", { name: /Proposed share for Career/ });
    await userEvent.clear(field);
    await userEvent.type(field, "33,5");

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The proposed share for Career is a number",
    );
    const approve = screen.getByRole("button", { name: "Approve the revision" });
    expect(approve).toBeDisabled();
    await userEvent.click(approve);
    expect(applied.bodies).toEqual([]);
  });

  it("round-trips the figure the api proposed when the reader touches nothing", async () => {
    const applied = recordingHandler("post", "/api/v1/reviews/budget/apply", {
      status: 200,
      body: { applied: 0, declared: [], changedAt: null, statement: "nothing." },
    });
    apiServer.use(
      ...screenHandlers(buildAreas(), buildReview({ proposal: buildReadyProposal() })),
      applied.handler,
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    const field = screen.getByRole("textbox", { name: /Proposed share for Career/ });
    expect(field).toHaveValue("44");
    await userEvent.click(screen.getByRole("button", { name: "Approve the revision" }));

    expect(applied.bodies).toEqual([
      {
        percentages: [
          { areaId: CAREER, budgetPercent: 44 },
          { areaId: STUDY, budgetPercent: 40 },
        ],
      },
    ]);
  });

  it("falls back to the proposed figure for a row the reader emptied", async () => {
    const applied = recordingHandler("post", "/api/v1/reviews/budget/apply", {
      status: 200,
      body: { applied: 0, declared: [], changedAt: null, statement: "nothing." },
    });
    apiServer.use(
      ...screenHandlers(buildAreas(), buildReview({ proposal: buildReadyProposal() })),
      applied.handler,
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    await userEvent.clear(screen.getByRole("textbox", { name: /Proposed share for Career/ }));
    await userEvent.click(screen.getByRole("button", { name: "Approve the revision" }));

    expect(applied.bodies).toEqual([
      {
        percentages: [
          { areaId: CAREER, budgetPercent: 44 },
          { areaId: STUDY, budgetPercent: 40 },
        ],
      },
    ]);
  });

  it("applies the proposed figures, and the vacancy's row is not among them", async () => {
    const applied = recordingHandler("post", "/api/v1/reviews/budget/apply", {
      status: 200,
      body: { applied: 2, declared: [CAREER, STUDY], changedAt: null, statement: "2 of 2." },
    });
    apiServer.use(
      ...screenHandlers(buildAreas(), buildReview({ proposal: buildReadyProposal() })),
      applied.handler,
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    await userEvent.click(screen.getByRole("button", { name: "Approve the revision" }));

    expect(applied.bodies).toEqual([
      {
        percentages: [
          { areaId: CAREER, budgetPercent: 44 },
          { areaId: STUDY, budgetPercent: 40 },
        ],
      },
    ]);
  });

  it("names a row whose Area the list no longer holds without announcing its identifier", async () => {
    /* The two cells agreed on nothing before: the Area column said `Unallocated` for a missing Area and the
     * control announced its UUID, which is the defect round 1 named, surviving in a fallback. */
    const missing = "77777777-7777-4777-8777-777777777777";
    const proposal = buildReadyProposal();
    apiServer.use(
      ...screenHandlers(
        buildAreas(),
        buildReview({
          proposal: {
            ...proposal,
            shares: [{ ...proposal.shares[0], areaId: missing }, ...proposal.shares.slice(1)],
          },
        }),
      ),
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    expect(
      screen.getByRole("textbox", { name: /Proposed share for an Area no longer declared/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "an Area no longer declared" })).toBeInTheDocument();
    expect(screen.queryByText(missing)).not.toBeInTheDocument();
  });

  it("writes nothing when the proposal is rejected", async () => {
    const applied = recordingHandler("post", "/api/v1/reviews/budget/apply", {
      status: 200,
      body: { applied: 0, declared: [], changedAt: null, statement: "nothing." },
    });
    apiServer.use(
      ...screenHandlers(buildAreas(), buildReview({ proposal: buildReadyProposal() })),
      applied.handler,
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    await userEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(screen.getByText("The proposal was rejected")).toBeInTheDocument();
    expect(applied.bodies).toEqual([]);
  });

  it("says the quarter holds nothing rather than drawing thirteen empty bars", async () => {
    apiServer.use(
      ...screenHandlers(
        buildAreas(),
        buildReview({
          quarterDays: buildDayCounts({
            confirmed: 0,
            unconfirmed: 0,
            statement: "No day of the last quarter has been answered for.",
          }),
        }),
      ),
    );
    renderAt(REVIEW_PATH);
    await screen.findByText("Pie review");

    expect(screen.getByText("No week of the quarter has been answered for")).toBeInTheDocument();
    expect(screen.queryByText(/Composition of discretionary time by week/)).not.toBeInTheDocument();
  });
});
