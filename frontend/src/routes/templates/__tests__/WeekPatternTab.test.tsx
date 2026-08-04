/* The week pattern tab: what is stored, and the control that replaces it whole.
 *
 * The partial mapping is the case worth most of these. A weekday with no day type materializes nothing, so six
 * sevenths of a pattern is not a pattern, and the control says so before a request is sent rather than after. */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { WeekPatternTab } from "../tabs/WeekPatternTab";
import { WEEKDAY_KEYS, weekdayLabel } from "../labels";
import { withRouter } from "./render";
import { writeDouble } from "./writeDouble";
import { DAY_TYPE_WEEKEND, buildDayType, buildWeekPattern } from "./fixtures";
import type { WeekPatternBody } from "../../../api/hooks/useWeekPattern";
import type { Problem } from "../../../contract";

const problem: Problem = {
  type: "syncr:validation-failed",
  title: "Validation failed",
  status: 422,
  detail: "Every weekday names a day type. Nothing was changed.",
  errors: [{ field: "sunday", message: "field required" }],
};

const dayTypes = [buildDayType(), buildDayType({ id: DAY_TYPE_WEEKEND, name: "Weekend" })];

function renderTab(overrides: Partial<Parameters<typeof WeekPatternTab>[0]> = {}) {
  const declaration = writeDouble<WeekPatternBody>();
  const result = render(
    withRouter(
      <WeekPatternTab
        pattern={{ status: "ready", data: buildWeekPattern() }}
        dayTypes={{ status: "ready", data: dayTypes }}
        write={declaration.write}
        {...overrides}
      />,
    ),
  );
  return { declaration, ...result };
}

const patternTable = () => screen.getByRole("table", { name: "The declared week pattern" });

describe("the declared pattern", () => {
  it("states all seven weekdays, in week order", () => {
    renderTab();

    const rows = within(patternTable()).getAllByRole("row").slice(1, 8);
    const weekdays = rows.map((row) => within(row).getAllByRole("cell")[0].textContent);

    expect(weekdays).toEqual([
      "Monday",
      "Tuesday",
      "Wednesday",
      "Thursday",
      "Friday",
      "Saturday",
      "Sunday",
    ]);
  });

  it("names each weekday's day type", () => {
    renderTab();

    const sunday = within(patternTable()).getAllByRole("row")[7];
    expect(within(sunday).getAllByRole("cell")[1]).toHaveTextContent("Weekend");
  });

  /* The api answers 404 until a pattern is declared, which is a first-run answer rather than a failure: seven
   * rows reading `not declared` beats an error surface saying something is broken. */
  it("reads every weekday as not declared before a pattern exists", () => {
    renderTab({ pattern: { status: "ready", data: null } });

    const cells = within(patternTable()).getAllByRole("cell");
    expect(cells.filter((cell) => cell.textContent === "not declared")).toHaveLength(7);
    expect(patternTable()).toHaveTextContent("none mapped yet");
  });

  it("says so when a weekday names a day type this tenant no longer has", () => {
    renderTab({ dayTypes: { status: "ready", data: [buildDayType()] } });

    expect(patternTable()).toHaveTextContent("a day type you no longer have");
  });
});

describe("declaring the pattern", () => {
  /* THE CONTROLS ARE ASSERTED, NOT ONLY THE DRAFT. Every other assertion here is driven by the draft, so an
   * editor rendering five selects would still refuse a partial mapping, still name the two weekdays left, and
   * still submit all seven from a declared pattern: a first-run reader would be told to choose two weekdays with
   * no control to choose them. */
  it("offers one control per weekday, named for that weekday", () => {
    renderTab({ pattern: { status: "ready", data: null } });

    for (const weekday of WEEKDAY_KEYS) {
      expect(
        screen.getByRole("combobox", { name: new RegExp(weekdayLabel(weekday)) }),
      ).toBeInTheDocument();
    }
    expect(screen.getAllByRole("combobox")).toHaveLength(WEEKDAY_KEYS.length);
  });

  it("carries a changed weekday into the body", async () => {
    const { declaration } = renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: /Monday/ }));
    await userEvent.click(screen.getByRole("option", { name: "Weekend" }));
    await userEvent.click(screen.getByRole("button", { name: "Declare the pattern" }));

    expect(declaration.bodies).toEqual([buildWeekPattern({ monday: DAY_TYPE_WEEKEND })]);
  });

  it("cannot submit a partial mapping, and names the weekdays still to choose", async () => {
    const { declaration } = renderTab({ pattern: { status: "ready", data: null } });
    const declare = screen.getByRole("button", { name: "Declare the pattern" });

    expect(declare).toBeDisabled();
    await userEvent.click(declare);

    expect(declaration.bodies).toEqual([]);
    expect(screen.getByText(/Still to choose: Monday, Tuesday/)).toBeInTheDocument();
  });

  /* One weekday of seven chosen is not one seventh of a pattern: the control is still inert, and the six
   * remaining weekdays are named rather than counted. */
  it("stays inert once one weekday of seven names a day type", async () => {
    const { declaration } = renderTab({ pattern: { status: "ready", data: null } });

    await userEvent.click(screen.getByRole("combobox", { name: /Monday/ }));
    await userEvent.click(screen.getByRole("option", { name: "Weekday" }));

    expect(screen.getByRole("button", { name: "Declare the pattern" })).toBeDisabled();
    expect(
      screen.getByText("Still to choose: Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday."),
    ).toBeInTheDocument();
    expect(declaration.bodies).toEqual([]);
  });

  it("is live once every weekday names a day type, and says nothing is still to choose", async () => {
    const { declaration } = renderTab();

    expect(screen.queryByText(/Still to choose/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Declare the pattern" }));

    expect(declaration.bodies).toEqual([buildWeekPattern()]);
  });

  /* The absence a reader would otherwise read as a missing feature: there is nowhere to put a repeat rule here,
   * because cadence is a property of a habit. */
  it("states that cadence is not expressible here, and where it lives", () => {
    renderTab();

    expect(
      screen.getByText(/Cadence is not expressible here: it lives on a habit/),
    ).toBeInTheDocument();
  });

  it("renders a refusal with the api's own sentence", () => {
    const declaration = writeDouble<WeekPatternBody>(problem);
    renderTab({ write: declaration.write });

    expect(screen.getByRole("status")).toHaveTextContent("sunday field required");
    expect(screen.getByRole("status")).toHaveTextContent("the pattern the plan is built from");
  });
});

describe("the tab's three static states", () => {
  it("states what is outstanding while a read is in flight", () => {
    renderTab({ dayTypes: { status: "loading" } });

    expect(screen.getByRole("status")).toHaveTextContent("Reading your week pattern");
  });

  it("names the read that failed", () => {
    renderTab({ pattern: { status: "error", problem } });

    expect(screen.getByRole("alert")).toHaveTextContent("The week pattern could not be read");
  });

  it("points a tenant with no day type at setup, because a mapping needs something to map to", () => {
    renderTab({ dayTypes: { status: "ready", data: [] } });

    expect(screen.getByText("No day type is declared")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to setup" })).toHaveAttribute("href", "/setup");
  });
});
