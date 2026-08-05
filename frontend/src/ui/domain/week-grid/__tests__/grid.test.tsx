/* THE GRID AS A WHOLE, THE STRIP ABOVE IT, AND THE TWO STATES THAT REPLACE IT.
 *
 * What a rendering can answer here is composition: seven columns from seven days, one axis for all of them, an hour
 * label on every hour line, a band under every block, and a strip that reserves its height whether or not it has a
 * verdict. The paint is a browser's business and the declarations are the stylesheet tests'. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EmptyWeek } from "../EmptyWeek";
import { SummaryStrip } from "../SummaryStrip";
import { TimeAxis } from "../TimeAxis";
import { WeekGrid } from "../WeekGrid";
import { GRID_H_PX } from "../metrics";
import type { Extent, GridBlock, StripReadings, WeekDay } from "..";

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

const READINGS: StripReadings = {
  scheduledMinutes: 4848,
  discretionaryMinutes: 3126,
  unallocatedMinutes: 1104,
  blockCount: 91,
  planCurrency: "current",
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
  it("reserves its height whether or not there is a verdict, so the grid cannot shift", () => {
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

    expect(withVerdict.container.querySelector(".strip--fixed")).not.toBeNull();
    expect(without.container.querySelector(".strip--fixed")).not.toBeNull();
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
    render(
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
    render(
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

  it("names the missing input by rendering the server's statement rather than a wording of its own", () => {
    render(
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
    const { container } = render(
      <EmptyWeek
        {...actions}
        reason="outside_horizon"
        setupHref="/setup"
        statement="Beyond the horizon."
      />,
    );

    expect(container.innerHTML).not.toMatch(/spin|shimmer|skeleton|pulse|progress/i);
  });
});
