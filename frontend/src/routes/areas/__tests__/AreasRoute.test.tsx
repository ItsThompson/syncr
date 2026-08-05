/* Rendering the Areas screen, and the parts of it only a DOM can answer for.
 *
 * FOUR THINGS ARE ASSERTED HERE AND NOWHERE ELSE. The two chart rules, because both are about what reaches the
 * markup rather than about what a function returns: hatch is always on, and a deviation row carries no Area ink
 * anywhere including its label cell. The preference cell's edit path, because it is an interaction. And the
 * mode, because "reachable by URL" is a claim about the route table.
 *
 * THE COBALT GUARD IS BOUNDED BY THE INVENTORY OF WHAT MAY EXIST, not by a vocabulary of what may not: it reads
 * every element of the deviation figure and refuses any class the CHART FAMILY paints an Area with, plus the
 * chip class the ledger uses. A guard written as a list of forbidden strings would pass the first time the kit
 * renamed one.
 *
 * IT QUERIES THE CHANNEL A READER PERCEIVES. Hatch is a `background-image` on a segment and a `fill` on a
 * wedge, so the assertions read those attributes rather than a prop or a constant the implementation also
 * reads. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { RequestHandler } from "msw";

import { apiServer } from "../../../testing/apiServer";
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
  buildReadyProposal,
  buildReview,
  buildThirteenAreas,
} from "./fixtures";
import type { Areas } from "../../../api/hooks/useAreas";
import type { BudgetReview } from "../../../api/hooks/useBudgetReview";

/** The screen reads the week it is in, so the handler answers whichever week the run falls in. */
const PERIOD = thisIsoWeek(new Date());
const REVIEW_URL = `/api/v1/reviews/budget?period=${PERIOD}`;

/** Every class the chart family paints an Area's own ink with, plus the ledger's chip. */
const AREA_INK_CLASSES = ["chart-fill", "chart-fill--hatched", "area-chip", "chip", "area-name"];

/* A `figure` carries no accessible name from its own `figcaption` under this accname implementation, so a
 * chart is located by the caption it draws and read through the figure that holds it. Asserting through the
 * caption is also the stronger reading: it is the text a reader sees above the chart. */
function chartWithCaption(caption: RegExp): HTMLElement {
  const found = screen.getByText(caption).closest("figure.chart");
  if (found === null) throw new Error(`no chart draws a caption matching ${caption}`);
  return found as HTMLElement;
}

function screenHandlers(areas: Areas, review: BudgetReview): RequestHandler[] {
  return [
    readyz(),
    jsonHandler("/api/v1/areas", { status: 200, body: areas }),
    jsonHandler(REVIEW_URL, { status: 200, body: review }),
    ...areas.areas.map((area) =>
      jsonHandler(`/api/v1/areas/${area.id}/preference`, {
        status: 200,
        body: area.id === CAREER ? buildPreference() : buildNoPreference(area.id),
      }),
    ),
  ];
}

async function renderAreas(
  { areas = buildAreas(), review = buildReview(), path = "/areas" } = {},
  extra: RequestHandler[] = [],
) {
  apiServer.use(...screenHandlers(areas, review), ...extra);
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
    const panel = screen.getByRole("region", { name: "Actual against target" });
    for (const element of panel.querySelectorAll("*")) {
      for (const painted of AREA_INK_CLASSES) {
        expect([...element.classList]).not.toContain(painted);
      }
      expect(element.getAttribute("style") ?? "").not.toMatch(/--area-|--ai\b|--hx\b/);
    }
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
});

describe("declaring an Area", () => {
  it("states how many of the twelve pigments are in use", async () => {
    await renderAreas();

    expect(screen.getByText("2 of 12 pigments in use")).toBeInTheDocument();
  });

  it("states that identity rests on the hatch and the name once a step repeats", async () => {
    const areas = buildThirteenAreas();
    await renderAreas({
      areas,
      review: buildReview({
        categories: areas.areas.map((area) => buildCategory({ areaId: area.id })),
      }),
    });

    expect(screen.getByText(areas.ramp.statement as string)).toBeInTheDocument();
    expect(screen.getByText("12 of 12 pigments in use")).toBeInTheDocument();
  });

  it("offers no colour control of any kind, because a pigment is dealt", async () => {
    await renderAreas();

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    const labels = within(form)
      .getAllByRole("textbox")
      .concat(within(form).getAllByRole("spinbutton"))
      .map((field) => field.getAttribute("aria-label") ?? field.id);

    expect(labels.join(" ").toLowerCase()).not.toMatch(/colour|color|pigment/);
  });

  it("sends the name, the floor and the share it was given", async () => {
    const created = recordingHandler("post", "/api/v1/areas", {
      status: 201,
      body: { area: buildAreas().areas[0], ramp: buildAreas().ramp },
    });
    await renderAreas({}, [created.handler]);

    const form = screen.getByRole("form", { name: "Declaring an Area" });
    await userEvent.type(within(form).getByRole("textbox"), "Research");
    await userEvent.click(within(form).getByRole("button", { name: "Declare it" }));

    expect(created.bodies).toEqual([
      { name: "Research", parentId: null, budgetPercent: null, floorHours: null },
    ]);
  });
});

describe("the preference cell", () => {
  it("reads the form the ticket names, and states where the preference came from", async () => {
    const table = await renderAreas();

    const row = within(table).getByRole("row", { name: /Career/ });
    expect(within(row).getByRole("button", { name: "05:30 \u00b7 strong" })).toBeInTheDocument();
    expect(within(row).getByText(/Set on this area/)).toBeInTheDocument();
  });

  it("reads a dash for an Area with no preference in effect", async () => {
    const table = await renderAreas();

    const row = within(table).getByRole("row", { name: /Study/ });
    expect(within(row).getByRole("button", { name: "\u2014" })).toBeInTheDocument();
  });

  it("edits in place, and sends the whole preference rather than the field that changed", async () => {
    const declared = recordingHandler("put", `/api/v1/areas/${CAREER}/preference`, {
      status: 200,
      body: buildPreference(),
    });
    const table = await renderAreas({}, [declared.handler]);

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(within(row).getByRole("button", { name: "05:30 \u00b7 strong" }));

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
    await userEvent.click(within(row).getByRole("button", { name: "05:30 \u00b7 strong" }));

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    expect(within(form).getByText("Daily cap")).toBeInTheDocument();
  });

  it("removes the declaration through its own act, which is not an empty window list", async () => {
    const removed = recordingHandler("put", `/api/v1/areas/${CAREER}/preference`, {
      status: 200,
      body: buildPreference(),
    });
    const table = await renderAreas({}, [removed.handler]);

    const row = within(table).getByRole("row", { name: /Career/ });
    await userEvent.click(within(row).getByRole("button", { name: "05:30 \u00b7 strong" }));

    const form = await screen.findByRole("form", { name: /Placement preference for Career/ });
    expect(
      within(form).getByRole("button", { name: "Remove the declaration" }),
    ).toBeInTheDocument();
  });

  it("opens one editor at a time, because a cell is edited in the row it belongs to", async () => {
    const table = await renderAreas();

    await userEvent.click(
      within(within(table).getByRole("row", { name: /Career/ })).getByRole("button", {
        name: "05:30 \u00b7 strong",
      }),
    );
    await userEvent.click(
      within(within(table).getByRole("row", { name: /Study/ })).getByRole("button", {
        name: "\u2014",
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
    /* One adjustable field per Area row and none for the vacancy, which is not an Area to write a share to. */
    expect(screen.getAllByRole("spinbutton", { name: /Proposed share for/ })).toHaveLength(2);
    expect(screen.getByText(/never re-cuts the budget on its own/)).toBeInTheDocument();
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
