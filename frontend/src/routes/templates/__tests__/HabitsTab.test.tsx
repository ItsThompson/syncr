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
import { step } from "./step";
import { writeDouble } from "./writeDouble";
import { HABIT_ANKI, HABIT_GYM, buildAreas, buildFixedHabit, buildHabit } from "./fixtures";
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

/* The api's own sentences, so a test cannot pass against wording only this screen would produce. */
const CURSOR_STATEMENT = buildHabit().cursor?.statement ?? "";
const DEBT_STATEMENT = buildHabit().debt.statement;

/* THE CONTROLS THIS TAB OFFERS, ENUMERATED, RATHER THAN THE ONES IT MAY NOT.
 *
 * A pattern is bounded by its vocabulary, and that bound is reachable: `Reset the debt` sets a derivation without
 * using a word a pattern could safely forbid, because `debt` on its own also matches the legitimate `Debt cap`,
 * and `Advance to Chest & Back` sets the cursor by naming the content rather than the member. Both are plausible
 * wordings and both pass a word list.
 *
 * An inventory reds on ANY control this tab does not already offer, whatever it is called, which is the claim the
 * ticket actually makes: these controls and no others. Adding one legitimately means adding it here,
 * deliberately, on a form whose whole point is what it does not offer.
 *
 * The names are the ACCESSIBLE names, computed rather than guessed: the required mark is part of the label, and
 * the computation joins the label's text nodes without a separator, so `Title` with a required mark is `Title*`.
 * The list is the inventory for the DEFAULT render, where the selected habit's cadence is a weekly count; a daily
 * habit offers no count box, which `hides the count box for a daily cadence` owns. */
const CONTROL_INVENTORY = [
  ["textbox", ["Title*", "Times a week*", "Debt cap*"]],
  ["combobox", ["Cadence", "On miss"]],
  ["spinbutton", ["Least", "Most"]],
  ["radio", []],
  ["checkbox", []],
  [
    "button",
    [
      "Gym",
      "Anki",
      "decrease 15 minutes",
      "decrease 15 minutes",
      "increase 15 minutes",
      "increase 15 minutes",
      "Save the habit",
    ],
  ],
] as const;

/** How many times a sentence appears inside a surface, which is what catches a restatement. */
function occurrencesIn(surface: HTMLElement, sentence: string): number {
  return (surface.textContent ?? "").split(sentence).length - 1;
}

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
    expect(derivations()).toHaveTextContent(CURSOR_STATEMENT);
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

describe("the two derivations are readings and not controls", () => {
  it("renders the cursor's own sentence, and does not restate it", () => {
    renderTab();

    /* The api's statement already names the variant and already says there is no control. Rendering it as it
     * arrives is the whole contract of the field, so the panel holds it once and adds nothing. Counted rather
     * than asserted for presence, because a restatement is still present. */
    expect(within(derivations()).getByText(CURSOR_STATEMENT)).toBeInTheDocument();
    expect(occurrencesIn(derivations(), "On Legs")).toBe(1);
    expect(occurrencesIn(derivations(), "no control to set it")).toBe(1);
  });

  /* THE ABSENCE IS ASSERTED AS AN INVENTORY, which is the only form that does not depend on guessing what a
   * control for a derived value would be called. Every name is queried by ROLE and NAME, because the accessible
   * name is the channel a reader perceives and the one channel every control shape here reaches: an Input, a
   * Select, a NumberStepper and a TimeInput are named by the label a FormRow mints, and carry no aria-label and
   * no text of their own.
   *
   * Both positive halves stay. Without them this passes on a tab that renders no derivation at all. */
  it.each(CONTROL_INVENTORY)(
    "offers exactly the %s controls this tab is meant to have, and none for either derivation",
    (role, names) => {
      renderTab();

      expect(derivations()).toHaveTextContent(CURSOR_STATEMENT);
      expect(habitTable()).toHaveTextContent("Legs \u00B7 derived");

      expect(screen.queryAllByRole(role)).toHaveLength(names.length);
      for (const name of new Set(names)) {
        expect(screen.queryAllByRole(role, { name })).toHaveLength(
          names.filter((each) => each === name).length,
        );
      }
    },
  );

  it("states the debt in the api's own words rather than restating the arithmetic", () => {
    renderTab();

    expect(derivations()).toHaveTextContent(DEBT_STATEMENT);
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

    await step("Most", "increase");
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
  /* The tab reads the ramp beside the Areas but draws no sentence from it: what separates two
   * Areas is stated by the kit, not rendered here. */
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
