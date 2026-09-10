/* THE GRID AS A WHOLE, THE STRIP ABOVE IT, AND THE TWO STATES THAT REPLACE IT.
 *
 * What a rendering can answer here is composition: seven columns from seven days, one axis for all of them, an hour
 * label on every hour line, a band under every block, and a strip that reserves its height whether or not it has a
 * verdict. The paint is a browser's business and the declarations are the stylesheet tests'. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { EmptyWeek } from "../EmptyWeek";
import { SummaryStrip } from "../SummaryStrip";
import { TimeAxis } from "../TimeAxis";
import { WeekGrid } from "../WeekGrid";
import { DAY_HEADER_H_PX, GRID_H_PX } from "../metrics";
import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { offeredRect } from "../../../../testing/layoutStubs";
import type { ReactElement } from "react";

import type { DayMark, Extent, GridBlock, StripReadings, WeekDay } from "..";
import type { Notice } from "../../notices";

const EXTENT: Extent = { startMin: 300, endMin: 1440 };
const DATES = [
  "2026-02-09",
  "2026-02-10",
  "2026-02-11",
  "2026-02-12",
  "2026-02-13",
  "2026-02-14",
  "2026-02-15",
];

function block(id: string, startMin: number, endMin: number): GridBlock {
  return {
    id,
    title: id,
    span: { startMin, endMin },
    origin: "task",
    pigment: "01",
    areaName: "Career",
    isPinned: false,
  };
}

function day(date: string, blocks: readonly GridBlock[] = []): WeekDay {
  return {
    date,
    zone: "Europe/London",
    startMs: Date.parse(`${date}T00:00:00Z`),
    minutes: 1440,
    blocks,
    bands: [],
  };
}

/** The one canvas a single-column grid draws, whose height is where a clamped zoom is observable. */
const canvasHeightOf = (container: Element): string =>
  (container.querySelector(".week-day__canvas") as HTMLElement).style.height;

/* Both of the empty week's destinations are routes this application owns, so both are `Link`s and both need a router:
 * a raw `href` would reload the document to reach a screen already in memory. */
const renderEmpty = (element: ReactElement) => render(<MemoryRouter>{element}</MemoryRouter>);

const READINGS: StripReadings = {
  scheduledMinutes: 4848,
  discretionaryMinutes: 3126,
  unallocatedMinutes: 1104,
  blockCount: 91,
  planCurrency: "current",
};

const STALE_DAY_MARK: DayMark = {
  pigment: "amber",
  notice: {
    id: "calendar-source-unreadable:source:2026-02-09",
    volume: "inline",
    pigment: "amber",
    title: "A calendar source could not be read",
    detail: "Imported commitments on this day may be out of date.",
    unavailable: ["reading new commitments from this calendar source"],
    stillWorks: ["the plan on the grid"],
    since: null,
    action: null,
    scope: { screen: "/week", date: DATES[0] },
  } satisfies Notice,
};

const UNCONFIRMED_DAY_MARK: DayMark = {
  ...STALE_DAY_MARK,
  pigment: "info",
  notice: { ...STALE_DAY_MARK.notice, id: "day-unconfirmed:2026-02-09", pigment: "info" },
};

describe("the grid's composition", () => {
  it("draws one column per day and one axis for all of them", () => {
    const { container } = render(
      <WeekGrid
        days={DATES.map((date) => day(date))}
        extent={EXTENT}
        labels={DATES}
        nowMs={null}
        visibleHours={12}
      />,
    );

    expect(container.querySelectorAll(".week-day")).toHaveLength(7);
    expect(container.querySelectorAll(".week-grid__axis")).toHaveLength(1);
  });

  it("gives every column the same canvas height, so an hour label lines up across the week", () => {
    const { container } = render(
      <WeekGrid
        days={DATES.map((date) => day(date))}
        extent={EXTENT}
        labels={DATES}
        nowMs={null}
        visibleHours={12}
      />,
    );
    const heights = [...container.querySelectorAll(".week-day__canvas")].map(
      (canvas) => (canvas as HTMLElement).style.height,
    );

    expect(new Set(heights).size).toBe(1);
    expect(heights[0]).toBe(
      `${((EXTENT.endMin - EXTENT.startMin) * (GRID_H_PX / (12 * 60))).toFixed(3)}px`,
    );
  });

  it("counts the blocks in each column's own header", () => {
    const { container } = render(
      <WeekGrid
        days={[day(DATES[0], [block("a", 540, 600), block("b", 600, 660)]), day(DATES[1])]}
        extent={EXTENT}
        labels={["MON 09", "TUE 10"]}
        nowMs={null}
        visibleHours={12}
      />,
    );
    const counts = [...container.querySelectorAll(".week-day__count")].map(
      (node) => node.textContent,
    );

    expect(counts).toEqual(["2", "0"]);
  });

  it("keeps a block's geometry identical when its header gains a mark", () => {
    const draw = (marks: readonly DayMark[]) => {
      const { container } = render(
        <WeekGrid
          days={[{ ...day(DATES[0], [block("a", 540, 600)]), marks }]}
          extent={EXTENT}
          labels={[DATES[0]]}
          nowMs={null}
          visibleHours={12}
        />,
      );
      const rendered = container.querySelector(".week-block");

      return {
        canvasHeight: canvasHeightOf(container),
        top: (rendered as HTMLElement).style.top,
        height: (rendered as HTMLElement).style.height,
        tier: rendered?.getAttribute("data-tier"),
      };
    };

    expect(draw([])).toEqual(draw([STALE_DAY_MARK]));
    expect(draw([])).toEqual(draw([UNCONFIRMED_DAY_MARK]));
  });

  it("draws the now rule in the ONE column holding the current instant, and in no other", () => {
    const nowMs = Date.parse(`${DATES[2]}T14:20:00Z`);
    const { container } = render(
      <WeekGrid
        days={DATES.map((date) => day(date))}
        extent={EXTENT}
        labels={DATES}
        nowMs={nowMs}
        visibleHours={12}
      />,
    );

    expect(container.querySelectorAll(".week-now")).toHaveLength(1);
    expect(container.querySelectorAll(".week-grid__now-time")).toHaveLength(1);
  });

  it("draws no now rule at all when the current instant is outside the week", () => {
    const { container } = render(
      <WeekGrid
        days={DATES.map((date) => day(date))}
        extent={EXTENT}
        labels={DATES}
        nowMs={Date.parse("2026-03-01T09:00:00Z")}
        visibleHours={12}
      />,
    );

    expect(container.querySelectorAll(".week-now")).toHaveLength(0);
  });

  it("draws every band BEFORE every block, which is what puts a band under one", () => {
    /* A band takes z-index 0 and a block takes none, so the two paint together in DOCUMENT ORDER. The order is
     * therefore the whole of "a band sits under every block", and a pinned block inside a recovery window still
     * reads as a block because of it. */
    const { container } = render(
      <WeekGrid
        days={[
          {
            ...day(DATES[0], [block("a", 540, 600)]),
            bands: [
              {
                id: "w1",
                span: { startMin: 500, endMin: 620 },
                label: "recovery",
                reason: "recovery",
              },
            ],
          },
        ]}
        extent={EXTENT}
        labels={["MON 09"]}
        nowMs={null}
        visibleHours={12}
      />,
    );
    const drawn = [...container.querySelectorAll(".week-band, .week-block")].map((node) =>
      node.classList.contains("week-band") ? "band" : "block",
    );

    expect(drawn).toEqual(["band", "block"]);
  });

  it("draws the now rule LAST, because it is a statement about every band and every block", () => {
    const { container } = render(
      <WeekGrid
        days={[day(DATES[0], [block("a", 540, 600)])]}
        extent={EXTENT}
        labels={["MON 09"]}
        nowMs={Date.parse(`${DATES[0]}T14:20:00Z`)}
        visibleHours={12}
      />,
    );
    const canvas = container.querySelector(".week-day__canvas");

    expect(canvas?.lastElementChild).toHaveClass("week-now");
  });

  it("renders roughly 210 blocks without virtualizing any of them", () => {
    const days = DATES.map((date) =>
      day(
        date,
        Array.from({ length: 30 }, (_, index) =>
          block(`${date}-${index}`, index * 30, index * 30 + 30),
        ),
      ),
    );
    const { container } = render(
      <WeekGrid days={days} extent={EXTENT} labels={DATES} nowMs={null} visibleHours={12} />,
    );

    expect(container.querySelectorAll(".week-block")).toHaveLength(210);
  });
});

describe("the axis", () => {
  it("labels every hour line inside the extent, in wall time", () => {
    render(
      <TimeAxis
        canvasHeightPx={626}
        extent={{ startMin: 480, endMin: 660 }}
        nowMin={null}
        pxPerMin={0.87}
      />,
    );

    expect(screen.getByText("08:00")).toBeInTheDocument();
    expect(screen.getByText("09:00")).toBeInTheDocument();
    expect(screen.getByText("11:00")).toBeInTheDocument();
  });

  it("continues into the next day past the end of one, which is the Sunday tail's own hours", () => {
    render(
      <TimeAxis
        canvasHeightPx={626}
        extent={{ startMin: 1380, endMin: 1860 }}
        nowMin={null}
        pxPerMin={0.87}
      />,
    );

    expect(screen.getByText("23:00")).toBeInTheDocument();
    expect(screen.getByText("00:00")).toBeInTheDocument();
    expect(screen.getByText("07:00")).toBeInTheDocument();
  });

  it("puts the now reading in the gutter rather than on the line", () => {
    const { container } = render(
      <TimeAxis canvasHeightPx={626} extent={EXTENT} nowMin={860} pxPerMin={0.87} />,
    );

    expect(container.querySelector(".week-grid__now-time")?.textContent).toBe("14:20");
  });
});

describe("the summary strip", () => {
  it("reserves its height whether or not there is a verdict, so the grid cannot shift", async () => {
    const withVerdict = render(
      <SummaryStrip
        readings={READINGS}
        verdict={{
          headline: "This week cannot hold its commitments",
          detail: "1h20m short on Career",
        }}
      />,
    );
    const without = render(<SummaryStrip readings={READINGS} verdict={null} />);

    /* The reservation is one declaration on the strip's own element, so both renderings carry the same class and
     * the sheet is what says the class holds a height. jsdom applies no stylesheet, so the height itself is read
     * out of the sheet rather than off the element. */
    expect(withVerdict.container.querySelector(".week-strip")).not.toBeNull();
    expect(without.container.querySelector(".week-strip")).not.toBeNull();
    expect(await kitStylesheet("week-grid/strip.css", domainDir)).toMatch(
      /\.week-strip \{[^}]*height: var\(--strip-h\)/,
    );
  });

  it("shows three readings plus the verdict, and nothing else", () => {
    const { container } = render(<SummaryStrip readings={READINGS} verdict={null} />);

    expect(container.querySelectorAll(".week-strip__cell")).toHaveLength(3);
    expect(container.querySelectorAll(".week-strip__verdict")).toHaveLength(1);
  });

  it("puts plan currency in the SCHEDULED cell's sub-line rather than in a fourth cell", () => {
    render(<SummaryStrip readings={{ ...READINGS, planCurrency: "solving" }} verdict={null} />);

    expect(screen.getByText("91 · solving")).toBeInTheDocument();
    expect(screen.getByText("80.8h")).toBeInTheDocument();
  });

  it("reads the count plainly when the plan is current", () => {
    render(<SummaryStrip readings={READINGS} verdict={null} />);

    expect(screen.getByText("91 blocks")).toBeInTheDocument();
  });

  it("names UNALLOCATED as one of the three, with its share of the denominator", () => {
    render(<SummaryStrip readings={READINGS} verdict={null} />);

    expect(screen.getByText("Unallocated")).toBeInTheDocument();
    expect(screen.getByText("35.3% of discretionary")).toBeInTheDocument();
  });

  it("names every subtrahend of the discretionary reading", () => {
    render(<SummaryStrip readings={READINGS} verdict={null} />);

    expect(
      screen.getByText("after frame, anchors, forbidden windows, and off-plan periods"),
    ).toBeInTheDocument();
  });

  it("states the verdict in words when it has one", () => {
    render(
      <SummaryStrip
        readings={READINGS}
        verdict={{
          headline: "This week cannot hold its commitments",
          detail: "1h20m short on Career",
        }}
      />,
    );

    expect(screen.getByText("This week cannot hold its commitments")).toBeInTheDocument();
    expect(screen.getByText("1h20m short on Career")).toBeInTheDocument();
  });
});

describe("the week with no plan", () => {
  const actions = { onSolveNow: vi.fn<() => void>(), extendHorizonHref: "/settings" };

  it("offers the horizon's two repairs, and states the server's own sentence", () => {
    renderEmpty(
      <EmptyWeek
        {...actions}
        reason="outside_horizon"
        setupHref="/setup"
        statement="This week is beyond your 14-day planning horizon."
      />,
    );

    expect(
      screen.getByText("This week is beyond your 14-day planning horizon."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Extend the horizon" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.getByRole("button", { name: "Solve this week now" })).toBeInTheDocument();
  });

  it("offers exactly one repair for a missing input, because there is one", () => {
    renderEmpty(
      <EmptyWeek
        {...actions}
        reason="setup_incomplete"
        setupHref="/setup"
        statement="Declare at least one Area and a day shape for each weekday."
      />,
    );

    expect(screen.getByRole("link", { name: "Finish setting up" })).toHaveAttribute(
      "href",
      "/setup",
    );
    expect(screen.queryByRole("button", { name: "Solve this week now" })).toBeNull();
  });

  /* THE WAITING STATE OFFERS THE SOLVE AND NOT THE HORIZON. The week is already inside the horizon, so widening it
   * repairs nothing, and the sentence the server composes for this state names the solve as the one thing a reader
   * can do to bring the plan forward. */
  it("states the wait for a week the horizon already holds, and offers only the solve", () => {
    renderEmpty(
      <EmptyWeek
        {...actions}
        reason="awaiting_maintainer"
        setupHref="/setup"
        statement="2026-W07 is inside your 14-day planning horizon and its plan has not been produced yet."
      />,
    );

    expect(screen.getByText("syncr is planning this week")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve this week now" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Extend the horizon" })).toBeNull();
  });

  it("names the missing input by rendering the server's statement rather than a wording of its own", () => {
    renderEmpty(
      <EmptyWeek
        {...actions}
        reason="setup_incomplete"
        setupHref="/setup"
        statement="Declare at least one Area and a day shape for each weekday."
      />,
    );

    expect(
      screen.getByText("Declare at least one Area and a day shape for each weekday."),
    ).toBeInTheDocument();
  });

  it("renders statically, with nothing that could spin", () => {
    const { container } = renderEmpty(
      <EmptyWeek
        {...actions}
        reason="outside_horizon"
        setupHref="/setup"
        statement="Beyond the horizon."
      />,
    );

    expect(container.innerHTML).not.toMatch(/spin|shimmer|skeleton|pulse|progress/i);
  });

  /* THE REPAIR ARRIVES AT THE SCREEN RATHER THAN RELOADING THE DOCUMENT, asserted by taking it.
   *
   * Both destinations are routes this application owns. A raw `<a href>` and a `Link` are indistinguishable by role,
   * by href and by name, which is why the first version of these tests could not see that the repairs shipped as raw
   * anchors: what separates them is that only one of the two NAVIGATES inside the application. Driven through a real
   * router, so the assertion is that the destination rendered. */
  it.each([
    ["setup_incomplete" as const, "Finish setting up", "the setup screen"],
    ["outside_horizon" as const, "Extend the horizon", "the settings screen"],
  ])("reaches %s's destination without reloading", async (reason, label, destination) => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/week"]}>
        <Routes>
          <Route
            element={
              <EmptyWeek
                {...actions}
                extendHorizonHref="/settings"
                reason={reason}
                setupHref="/setup"
                statement="No plan yet."
              />
            }
            path="/week"
          />
          <Route element={<p>the setup screen</p>} path="/setup" />
          <Route element={<p>the settings screen</p>} path="/settings" />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("link", { name: label }));

    expect(screen.getByText(destination)).toBeInTheDocument();
  });
});

/* THE CLAMP IS THE GRID'S, AGAINST THE HEIGHT IT MEASURES.
 *
 * Nothing is laid out in a headless DOM, so the arithmetic falls back to the reference display's grid and every other
 * test in this file reads that fallback. What these two assert is the WIRING: a measured height reaches the clamp, so
 * a 27 inch reader's stored 24 renders at 24 and a short window's does not render at a level the modal block cannot
 * hold. Clamping above this component made both impossible, and no test could see it because the constant and the
 * fallback are the same number.
 *
 * `getBoundingClientRect` is stubbed on the prototype rather than mocked on an instance, because the hook reads it
 * through the ref it observes and there is no instance to reach before the effect runs. The stub is the shared
 * `offeredRect`, which places a rect's top so the surface is `heightPx` above the viewport's bottom. */
describe("the clamp against a measured height", () => {
  function renderMeasuring(heightPx: number, visibleHours: number): string {
    const original = Object.getOwnPropertyDescriptor(Element.prototype, "getBoundingClientRect");
    Object.defineProperty(Element.prototype, "getBoundingClientRect", {
      configurable: true,
      value() {
        return offeredRect(heightPx);
      },
    });
    try {
      const { container } = render(
        <WeekGrid
          days={[day(DATES[0])]}
          extent={EXTENT}
          labels={[DATES[0]]}
          nowMs={null}
          visibleHours={visibleHours}
        />,
      );
      return canvasHeightOf(container);
    } finally {
      if (original === undefined)
        delete (Element.prototype as { getBoundingClientRect?: unknown }).getBoundingClientRect;
      else Object.defineProperty(Element.prototype, "getBoundingClientRect", original);
    }
  }

  it("offers the whole range on a display tall enough for it, rather than the reference cap", () => {
    /* A 27 inch grid measures 1136px, whose honest cap is 24. Clamped against the reference constant this renders at
     * 16, which is a third of the range taken away from the reader who paid for the display. */
    const grid = 1136 + DAY_HEADER_H_PX;
    const atTwentyFour = ((EXTENT.endMin - EXTENT.startMin) * (1136 / (24 * 60))).toFixed(3);

    expect(renderMeasuring(grid, 24)).toBe(`${atTwentyFour}px`);
  });

  it("caps a short window below the reference cap, where the modal block would lose its title", () => {
    /* 500px of grid caps at 13 hours: floor(500 * 30 / (19 * 60)). Clamped against the reference constant this would
     * render at 16, and a thirty-minute block would be 15.6px, below the 19px label floor. */
    const grid = 500 + DAY_HEADER_H_PX;
    const atThirteen = ((EXTENT.endMin - EXTENT.startMin) * (500 / (13 * 60))).toFixed(3);

    expect(renderMeasuring(grid, 24)).toBe(`${atThirteen}px`);
  });
});
