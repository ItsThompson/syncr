/* The habits tab: the table, the two derivations, and the editor.
 *
 * THE STRONGEST CLAIM HERE IS AN ABSENCE. No control on this tab sets the rotation cursor, and asserting that
 * needs both halves: that the cursor is rendered, so the test cannot pass because the word is missing
 * everywhere, and that not one control on the tab is named for it. */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { HabitsTab } from "../tabs/HabitsTab";
import { withRouter } from "./render";
import { writeDouble } from "./writeDouble";
import {
  HABIT_ANKI,
  HABIT_GYM,
  buildArea,
  buildAreas,
  buildFixedHabit,
  buildHabit,
  buildRamp,
} from "./fixtures";
import type { HabitEdit } from "../../../api/hooks/useHabits";
import type { Problem } from "../../../contract";

const problem: Problem = {
  type: "syncr:validation-failed",
  title: "Validation failed",
  status: 422,
  detail: "A weekly count of zero is not a cadence. Nothing was changed.",
  errors: [{ field: "cadence", message: "timesPerWeek must be at least 1" }],
};

function renderTab(overrides: Partial<Parameters<typeof HabitsTab>[0]> = {}) {
  const edit = writeDouble<HabitEdit>();
  const result = render(
    withRouter(
      <HabitsTab
        habits={{ status: "ready", data: [buildHabit(), buildFixedHabit()] }}
        areas={{ status: "ready", data: buildAreas() }}
        selectedId={HABIT_GYM}
        onSelect={() => {}}
        write={edit.write}
        {...overrides}
      />,
    ),
  );
  return { edit, ...result };
}

const habitTable = () => screen.getByRole("table", { name: /^Habits/ });
const rowFor = (title: string) =>
  within(habitTable())
    .getAllByRole("row")
    .find((row) => within(row).queryByRole("button", { name: title }) !== null);

const derivations = () => screen.getByRole("region", { name: "Derived, and read-only" });

describe("the habits table", () => {
  it("renders every column the ticket names", () => {
    renderTab();

    const headers = within(habitTable())
      .getAllByRole("columnheader")
      .map((header) => header.textContent);

    expect(headers).toEqual([
      "Habit",
      "Area",
      "Cadence",
      "Duration",
      "On miss",
      "Binding",
      "Debt",
      "Cursor",
    ]);
  });

  it("states the cadence, the duration, the miss policy and the binding source", () => {
    renderTab();
    const row = rowFor("Gym");

    expect(row).toHaveTextContent("4 / wk");
    expect(row).toHaveTextContent("1h");
    expect(row).toHaveTextContent("debt");
    expect(row).toHaveTextContent("rotation");
  });

  it("names the Area beside its chip, because colour alone identifies nothing", () => {
    renderTab();
    const row = rowFor("Gym");

    expect(row).toHaveTextContent("Fitness");
  });

  it("states the debt figure against its cap, which is what makes the figure mean anything", () => {
    renderTab();

    expect(rowFor("Gym")).toHaveTextContent("2 of 8");
  });

  it("renders the rotation cursor as a reading, and says it is derived", () => {
    renderTab();
    const row = rowFor("Gym");

    expect(row).toHaveTextContent("Legs \u00B7 derived");
  });

  /* The cell is one line because the row is 28px: the cursor's whole provenance sentence is rendered beside the
   * editor, where there is room for it. */
  it("keeps the cursor cell to one line, and puts the whole sentence beside the editor", () => {
    renderTab();

    expect(rowFor("Gym")).not.toHaveTextContent("was confirmed complete");
    expect(derivations()).toHaveTextContent(
      "Legs is next because Chest & Back was confirmed complete.",
    );
  });

  /* A fixed habit repeats one content, so there is no rotation to be at a position in. */
  it("shows no cursor at all for a fixed-source habit", () => {
    renderTab();
    const row = rowFor("Anki");

    expect(row).toHaveTextContent("\u2014");
    expect(row).not.toHaveTextContent("Legs");
  });

  it("reports the selected habit to its caller", async () => {
    const chosen: string[] = [];
    renderTab({ onSelect: (id) => chosen.push(id) });

    await userEvent.click(screen.getByRole("button", { name: "Anki" }));

    expect(chosen).toEqual([HABIT_ANKI]);
  });
});

describe("the cursor is a reading and not a control", () => {
  it("renders the cursor and its provenance beside the form", () => {
    renderTab();

    expect(derivations()).toHaveTextContent("Legs is next because Chest & Back was confirmed");
    expect(derivations()).toHaveTextContent("There is no control that sets one");
  });

  /* Both halves: the cursor IS on the screen, and not one control anywhere on the tab is named for it. Without
   * the first half this passes on a tab that renders no cursor at all. */
  it("offers no control that sets it, anywhere on the tab", () => {
    renderTab();

    expect(within(derivations()).getByText(/Legs is next because/)).toBeInTheDocument();
    expect(habitTable()).toHaveTextContent("Legs \u00B7 derived");

    const controls = [
      ...screen.queryAllByRole("textbox"),
      ...screen.queryAllByRole("combobox"),
      ...screen.queryAllByRole("spinbutton"),
      ...screen.queryAllByRole("radio"),
      ...screen.queryAllByRole("checkbox"),
      ...screen.queryAllByRole("button"),
    ];
    const named = controls.map(
      (control) => control.getAttribute("aria-label") ?? control.textContent ?? "",
    );

    expect(named.filter((name) => /cursor|variant|rotation/i.test(name))).toEqual([]);
  });

  it("states the debt in the api's own words rather than restating the arithmetic", () => {
    renderTab();

    expect(derivations()).toHaveTextContent("Two occurrences are owed, against a cap of eight.");
  });

  it("says a fixed habit has no cursor, rather than rendering an empty reading", () => {
    renderTab({ selectedId: HABIT_ANKI });

    expect(derivations()).toHaveTextContent("A fixed habit has no rotation, so it has no cursor");
  });
});

describe("editing a habit", () => {
  it("submits every member the patch shape carries, and neither derivation", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("button", { name: "Save the habit" }));

    expect(edit.bodies).toEqual([
      {
        title: "Gym",
        cadence: { kind: "times_per_week", timesPerWeek: 4 },
        minDurationMinutes: 60,
        maxDurationMinutes: 60,
        missPolicy: "debt",
        debtCapPeriods: 2,
      },
    ]);
  });

  it("carries a changed cadence count into the body", async () => {
    const { edit } = renderTab();

    const count = screen.getByRole("textbox", { name: /Times a week/ });
    await userEvent.clear(count);
    await userEvent.type(count, "5");
    await userEvent.click(screen.getByRole("button", { name: "Save the habit" }));

    expect(edit.bodies[0].cadence).toEqual({ kind: "times_per_week", timesPerWeek: 5 });
  });

  it("carries a changed title and a changed miss policy into the body", async () => {
    const { edit } = renderTab();

    const title = screen.getByRole("textbox", { name: /Title/ });
    await userEvent.clear(title);
    await userEvent.type(title, "Gym session");
    await userEvent.click(screen.getByRole("combobox", { name: /On miss/ }));
    await userEvent.click(screen.getByRole("option", { name: /escalate/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save the habit" }));

    expect(edit.bodies[0]).toMatchObject({ title: "Gym session", missPolicy: "escalate" });
  });

  it("carries a stepped duration into the body, which is what makes it elastic", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getAllByRole("button", { name: "increase 15 minutes" })[1]);
    await userEvent.click(screen.getByRole("button", { name: "Save the habit" }));

    expect(edit.bodies[0]).toMatchObject({ minDurationMinutes: 60, maxDurationMinutes: 75 });
  });

  it("carries a changed cadence kind, and offers the interval box for an approximate one", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: /Cadence/ }));
    await userEvent.click(screen.getByRole("option", { name: /roughly every N days/ }));
    const interval = screen.getByRole("textbox", { name: /Every N days/ });
    await userEvent.clear(interval);
    await userEvent.type(interval, "7");
    await userEvent.click(screen.getByRole("button", { name: "Save the habit" }));

    expect(edit.bodies[0].cadence).toEqual({ kind: "every_approx_days", approxDays: 7 });
  });

  it("carries a changed debt cap into the body", async () => {
    const { edit } = renderTab();

    const cap = screen.getByRole("textbox", { name: /Debt cap/ });
    await userEvent.clear(cap);
    await userEvent.type(cap, "4");
    await userEvent.click(screen.getByRole("button", { name: "Save the habit" }));

    expect(edit.bodies[0].debtCapPeriods).toBe(4);
  });

  it("hides the count box for a daily cadence, which carries no number", async () => {
    renderTab({ selectedId: HABIT_ANKI });

    expect(screen.queryByRole("textbox", { name: /Times a week/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Every N days/ })).not.toBeInTheDocument();
  });

  it("cannot be saved while a count is not a whole number, and says what one is", async () => {
    const { edit } = renderTab();

    const count = screen.getByRole("textbox", { name: /Times a week/ });
    await userEvent.clear(count);
    await userEvent.type(count, "four");

    expect(screen.getByRole("button", { name: "Save the habit" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save the habit" }));
    expect(edit.bodies).toEqual([]);
    expect(screen.getByText(/whole count of occurrences/)).toBeInTheDocument();
  });

  it("renders a refusal with the member the api named", () => {
    const edit = writeDouble<HabitEdit>(problem);
    renderTab({ write: edit.write });

    expect(screen.getByRole("status")).toHaveTextContent("cadence timesPerWeek must be at least 1");
    /* And again on the row that owns the member, which is where the reader is looking. */
    expect(screen.getByText("timesPerWeek must be at least 1").className).toContain(
      "form-row__message--error",
    );
  });
});

describe("the ramp reading", () => {
  /* Past twelve Areas the pigment repeats, so two chips in this table can be the same ink. The api states that
   * and this tab renders it: the wire carries the ramp step and not the position in the deal, so the frontend
   * cannot tell the two apart on its own. */
  it("states what identity rests on once two Areas share a step", () => {
    const areas = [
      buildArea({ id: "1", name: "Career", pigmentIndex: 0 }),
      buildArea({ id: "2", name: "Thirteenth", pigmentIndex: 0 }),
    ];
    renderTab({
      areas: {
        status: "ready",
        data: {
          areas,
          ramp: buildRamp({
            areasSharingAPigment: 2,
            statement: "Two Areas share a pigment, so identity rests on the name.",
          }),
        },
      },
      habits: {
        status: "ready",
        data: [buildHabit({ areaId: "1" }), buildFixedHabit({ areaId: "2" })],
      },
    });

    expect(
      screen.getByText("Two Areas share a pigment, so identity rests on the name."),
    ).toBeInTheDocument();
  });

  it("draws no footer at all while every Area holds its own step", () => {
    renderTab();

    expect(screen.getByRole("region", { name: "Habits" }).querySelector("footer")).toBeNull();
  });
});

describe("the tab's three static states", () => {
  it("states what is outstanding while a read is in flight", () => {
    renderTab({ habits: { status: "loading" } });

    expect(screen.getByRole("status")).toHaveTextContent("Reading your habits");
  });

  it("names the read that failed", () => {
    renderTab({ habits: { status: "error", problem } });

    expect(screen.getByRole("alert")).toHaveTextContent("The habits could not be read");
  });

  it("says what a habit is when none is declared", () => {
    renderTab({ habits: { status: "ready", data: [] } });

    expect(screen.getByText("No habit is declared")).toBeInTheDocument();
  });

  it("says so when nothing is selected, rather than rendering an empty editor", () => {
    renderTab({ selectedId: null });

    expect(screen.getByText("No habit is selected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save the habit" })).not.toBeInTheDocument();
  });
});
