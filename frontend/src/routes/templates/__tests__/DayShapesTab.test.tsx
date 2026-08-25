/* The day shapes tab: the list, the entries, and the form that declares one.
 *
 * The form's contract is the body it submits, so that is what these assert. The pairing rule is asserted from
 * both sides: a concrete entry cannot be declared without a binding, and a slot's body carries no binding at
 * all even though the same control changed nothing else. */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DayShapesTab } from "../tabs/DayShapesTab";
import { withRouter } from "./render";
import { step } from "./step";
import { writeDouble } from "./writeDouble";
import {
  AREA_CAREER,
  ROUTINE_WAKE,
  SHAPE_WEEKDAY,
  buildAreas,
  buildDayType,
  buildEntry,
  buildHabit,
  buildRoutine,
  buildShape,
  buildShapeSummary,
} from "./fixtures";
import type { EntryBody } from "../../../api/hooks/useTemplates";
import type { Problem } from "../../../contract";

const problem: Problem = {
  type: "syncr:validation-failed",
  title: "Validation failed",
  status: 422,
  detail: "A target time off the quarter hour is not a placement. Nothing was changed.",
  errors: [{ field: "targetTime", message: "must land on a 15-minute step of the grid" }],
};

function renderTab(overrides: Partial<Parameters<typeof DayShapesTab>[0]> = {}) {
  const declaration = writeDouble<EntryBody>();
  const result = render(
    withRouter(
      <DayShapesTab
        shapes={{ status: "ready", data: [buildShapeSummary()] }}
        dayTypes={{ status: "ready", data: [buildDayType()] }}
        areas={{ status: "ready", data: buildAreas() }}
        routines={{ status: "ready", data: [buildRoutine()] }}
        habits={{ status: "ready", data: [buildHabit()] }}
        shape={{ status: "ready", data: buildShape() }}
        selectedId={SHAPE_WEEKDAY}
        onSelect={() => {}}
        entryWrite={declaration.write}
        {...overrides}
      />,
    ),
  );
  return { declaration, ...result };
}

/** Chooses an option from a select named by its row's label. */
async function choose(label: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: new RegExp(label) }));
  await userEvent.click(screen.getByRole("option", { name: option }));
}

describe("the day shapes list", () => {
  it("states each shape's entry count and the day type it shapes", () => {
    renderTab();

    /* Read as the ROW's cells. A count asserted against the whole table passes on any `2` in it, including one in
     * a name or in the footer's own sentence. */
    const list = screen.getByRole("table", { name: "Day shapes" });
    const row = within(list).getAllByRole("row")[1];
    const cells = within(row)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);

    expect(cells).toEqual(["Weekday", "Weekday", "2"]);
  });

  it("says so when a shape names a day type this tenant no longer has", () => {
    renderTab({ dayTypes: { status: "ready", data: [] } });

    expect(screen.getByRole("table", { name: "Day shapes" })).toHaveTextContent(
      "a day type you no longer have",
    );
  });

  /* THE LIST DECLARES ITS COLUMNS, and the shape column is the one that absorbs the surplus: the other two
   * hold the widths they declare whatever any name beside them says, so a long name spends its own row's
   * height instead of moving its neighbours. Scoped to this table, because a sibling sheet in the tab may
   * declare its own columns one day. The widths are read from the style ATTRIBUTE because jsdom's style
   * object drops a value its parser does not understand, and `calc()` over mixed units is exactly such a
   * value. */
  it("declares the shape column as the one that absorbs the surplus", () => {
    renderTab();

    const table = screen.getByRole("table", { name: "Day shapes" });
    const widths = [...table.querySelectorAll("col")].map((col) => col.getAttribute("style"));

    expect(widths).toEqual(["width: calc(100% - (72px + 72px));", "width: 72px;", "width: 72px;"]);
  });

  /* A NAME AT THE API'S CAP IS RENDERED WHOLE, and this pins the refusal rather than the geometry. The list
   * declares its columns now, so a long name spends its own row's height inside the width its column was given,
   * and the row still grows past the table's 28px pitch: the height is what wrapping costs, not something to
   * hold down. Nothing truncates, because a truncated name is the one thing a reader picking a shape cannot
   * read; what this test refuses is a silent ellipsis ever appearing in place of that decision. */
  it("renders a name at the api's cap in full, rather than truncating it", () => {
    const name = "Weekday with lectures, a placement interview and a gym slot";
    renderTab({ shapes: { status: "ready", data: [buildShapeSummary({ name })] } });

    expect(name).toHaveLength(59);
    expect(screen.getByRole("button", { name })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Day shapes" })).toHaveTextContent(name);
  });

  it("reports the selected shape to its caller", async () => {
    const chosen: string[] = [];
    renderTab({ onSelect: (id) => chosen.push(id) });

    await userEvent.click(screen.getByRole("button", { name: "Weekday" }));

    expect(chosen).toEqual([SHAPE_WEEKDAY]);
  });
});

describe("the selected shape's entries", () => {
  it("renders the sheet's columns in the sheet's order", () => {
    renderTab();

    const table = screen.getByRole("table", { name: /entries this day shape holds/ });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);

    expect(headers).toEqual(["Target", "Kind", "Entry", "Area", "Duration", "Flex"]);
  });

  it("names the routine a concrete entry binds, and the Area of a slot", () => {
    renderTab();

    const table = screen.getByRole("table", { name: /entries this day shape holds/ });
    expect(table).toHaveTextContent("Wake Up");
    expect(table).toHaveTextContent("Career");
  });

  it("says a slot's content is bound at plan time rather than leaving the cell empty", () => {
    renderTab();

    expect(screen.getByRole("table", { name: /entries/ })).toHaveTextContent("bound at plan time");
  });

  it("reads a concrete entry with no Area as the frame, because a routine carries no Area", () => {
    renderTab();

    expect(screen.getByRole("table", { name: /entries/ })).toHaveTextContent("frame");
  });

  /* The shape read itself answers whether a binding still resolves (`contentResolves`), so the row renders the
   * dangling state from the report even while the routine and habit lists still hold other rows. */
  it("says so when the shape read reports an entry's content no longer resolves", () => {
    const shape = buildShape({ entries: [buildEntry({ contentResolves: false })] });
    renderTab({ shape: { status: "ready", data: shape } });

    expect(screen.getByRole("table", { name: /entries/ })).toHaveTextContent(
      "content you no longer have",
    );
  });

  it("names the content of an entry whose binding the shape read reports as held", () => {
    const shape = buildShape({ entries: [buildEntry({ contentResolves: true })] });
    renderTab({ shape: { status: "ready", data: shape } });

    expect(screen.getByRole("table", { name: /entries/ })).toHaveTextContent("Wake Up");
  });

  it("renders a flex band under one step as no shift, because it permits none", () => {
    const shape = buildShape({ entries: [buildEntry({ flexBandMinutes: 5 })] });
    renderTab({ shape: { status: "ready", data: shape } });

    /* Read as a CELL, not as the table's text. The footer carries its own sentence about every entry being fixed
     * by derivation, which is why the cell no longer says `fixed` at all: one word, one meaning. */
    const table = screen.getByRole("table", { name: /entries/ });
    expect(within(table).getByText("no shift")).toBeInTheDocument();
  });
});

describe("declaring a concrete entry", () => {
  it("submits the binding it names and no Area", async () => {
    const { declaration } = renderTab();

    await choose("Entry", "Wake Up \u00B7 routine");
    await userEvent.click(screen.getByRole("button", { name: "Declare entry" }));

    expect(declaration.bodies).toEqual([
      {
        kind: "concrete",
        targetTime: "07:00",
        durationMinutes: 60,
        flexBandMinutes: 0,
        bindingTarget: "routine",
        bindingRef: ROUTINE_WAKE,
      },
    ]);
  });

  it("carries a stepped duration and flex band into the body", async () => {
    const { declaration } = renderTab();

    await choose("Entry", "Wake Up \u00B7 routine");
    await step("Duration", "increase");
    await step("Flex band", "increase");
    await userEvent.click(screen.getByRole("button", { name: "Declare entry" }));

    expect(declaration.bodies[0]).toMatchObject({ durationMinutes: 75, flexBandMinutes: 15 });
  });

  it("snaps a typed target time to the quarter hour on commit", async () => {
    const { declaration } = renderTab();

    await choose("Entry", "Wake Up \u00B7 routine");
    const target = screen.getByLabelText(/Target/);
    await userEvent.clear(target);
    await userEvent.type(target, "07:07");
    await userEvent.tab();
    await userEvent.click(screen.getByRole("button", { name: "Declare entry" }));

    expect(declaration.bodies[0].targetTime).toBe("07:00");
  });

  it("offers habits as well as routines, because a concrete entry may name either", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: /Entry/ }));

    expect(screen.getByRole("option", { name: "Gym \u00B7 habit" })).toBeInTheDocument();
  });

  /* The form states the rule rather than discovering it: with no binding chosen there is no body to send, so the
   * control is inert and the row says which member to choose. */
  it("cannot be submitted with no binding, and names the member to choose", async () => {
    const { declaration } = renderTab();
    const declare = screen.getByRole("button", { name: "Declare entry" });

    expect(declare).toBeDisabled();
    await userEvent.click(declare);

    expect(declaration.bodies).toEqual([]);
    expect(screen.getByText(/names the routine or habit that happens/)).toBeInTheDocument();
  });

  it("offers no Area control at all, so an Area-only body cannot be assembled", () => {
    renderTab();

    expect(screen.queryByRole("combobox", { name: /Area/ })).not.toBeInTheDocument();
  });

  /* Named by the words the screen draws, not by a string of its own: a group carrying its own `aria-label`
   * beside the drawn question announces the same words twice. */
  it("names the kind group by the drawn question and no string of its own", () => {
    renderTab();

    const drawn = screen
      .getAllByText("Kind")
      .filter((element) => element.classList.contains("form-row__label"));
    expect(drawn).toHaveLength(1);

    const kind = screen.getByRole("radiogroup", { name: "Kind" });
    expect(kind).toHaveAttribute("aria-labelledby", drawn[0].id);
    expect(kind).not.toHaveAttribute("aria-label");
  });
});

describe("declaring a slot", () => {
  it("submits the Area it reserves and no binding", async () => {
    const { declaration } = renderTab();

    await userEvent.click(screen.getByRole("radio", { name: /^slot/ }));
    await choose("Area", "Career");
    await userEvent.click(screen.getByRole("button", { name: "Declare entry" }));

    expect(declaration.bodies).toEqual([
      {
        kind: "slot",
        targetTime: "07:00",
        durationMinutes: 60,
        flexBandMinutes: 0,
        areaId: AREA_CAREER,
      },
    ]);
  });

  it("offers no binding control, because a slot has nowhere to put one", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("radio", { name: /^slot/ }));

    expect(screen.queryByRole("combobox", { name: /Entry/ })).not.toBeInTheDocument();
  });

  it("cannot be submitted with no Area, and names the member to choose", async () => {
    const { declaration } = renderTab();

    await userEvent.click(screen.getByRole("radio", { name: /^slot/ }));
    await userEvent.click(screen.getByRole("button", { name: "Declare entry" }));

    expect(declaration.bodies).toEqual([]);
    expect(screen.getByText(/reserves time for one Area/)).toBeInTheDocument();
  });
});

describe("a refused declaration", () => {
  it("renders the api's sentence and the member it named", () => {
    const declaration = writeDouble<EntryBody>(problem);
    renderTab({ entryWrite: declaration.write });

    expect(screen.getByRole("status")).toHaveTextContent(
      "targetTime must land on a 15-minute step",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Nothing was changed");
    expect(screen.getByText("must land on a 15-minute step of the grid")).toBeInTheDocument();
  });

  it("says what still works, so a refusal is not read as an outage", () => {
    const declaration = writeDouble<EntryBody>(problem);
    renderTab({ entryWrite: declaration.write });

    expect(screen.getByRole("status")).toHaveTextContent("every entry this shape already holds");
  });
});

describe("the tab's three static states", () => {
  it("states what is outstanding while a read is in flight, rather than a bare surface", () => {
    renderTab({ shapes: { status: "loading" } });

    const pending = screen.getByRole("status");
    expect(pending).toHaveTextContent("Reading your day shapes");
    expect(pending).toHaveTextContent("The list, the selected shape's entries");
  });

  it("names the read that failed and keeps the api's own sentence", () => {
    renderTab({ areas: { status: "error", problem } });

    expect(screen.getByRole("alert")).toHaveTextContent("The Areas could not be read");
    expect(screen.getByRole("alert")).toHaveTextContent("A target time off the quarter hour");
  });

  it("points a tenant with no shape at setup, which is where the first one is built", () => {
    renderTab({ shapes: { status: "ready", data: [] } });

    expect(screen.getByText("No day shape is declared")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to setup" })).toHaveAttribute("href", "/setup");
  });

  it("says so when a shape is selected that has no entries yet", () => {
    renderTab({ shape: { status: "ready", data: buildShape({ entries: [] }) } });

    expect(screen.getByRole("table", { name: /entries/ })).toHaveTextContent("0 entries");
  });
});
