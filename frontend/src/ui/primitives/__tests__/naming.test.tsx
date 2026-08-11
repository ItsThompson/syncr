/* NAMING A CONTROL NO `<label>` CAN POINT AT.
 *
 * `../naming.ts` carries the reason neither control is labelable and what a browser computes for a group a
 * label aims at. What is asserted here is the consequence: each control takes either the words or the id of
 * an element the screen drew them in, and the two are not interchangeable. Both name the control, and a
 * rendering looks identical either way; what differs is how many times the words were WRITTEN, which is what
 * `authoredNames` reads and what the last case here pins. Chrome reports the same distinction as a name
 * source: `attribute[aria-label]` against `relatedElement[aria-labelledby]`.
 *
 * THE COMPILER CARRIES THE OTHER HALF. A control with no name is announced by its role alone, and a control
 * with two names has two strings to keep in step, so neither is representable: the cases below are
 * `@ts-expect-error` directives rather than assertions, and `tsc --noEmit` runs over `src`, so a directive
 * that stops erroring fails the typecheck. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { authoredNames } from "../../../testing/accessibleNames";
import { Radio, TimeRangeInput } from "../index";

const noop = () => {};

const OPTIONS = [
  { value: "concrete", label: "concrete" },
  { value: "slot", label: "slot" },
];

const BOUNDS = { start: "07:00", end: "22:00" };

describe("a radio group named by an element the screen drew", () => {
  it("takes its name from that element and carries no string of its own", () => {
    render(
      <>
        <span id="kind-question">Kind</span>
        <Radio labelledBy="kind-question" value="slot" onValueChange={noop} options={OPTIONS} />
      </>,
    );

    const group = screen.getByRole("radiogroup", { name: "Kind" });
    expect(group).toHaveAttribute("aria-labelledby", "kind-question");
    expect(group).not.toHaveAttribute("aria-label");
  });

  it("leaves the words written once, in the element the screen drew", () => {
    const { container } = render(
      <>
        <span id="kind-question">Kind</span>
        <Radio labelledBy="kind-question" value="slot" onValueChange={noop} options={OPTIONS} />
      </>,
    );

    expect(authoredNames(container, "Kind")).toEqual([{ source: "drawn text", by: "span" }]);
  });

  it("keeps naming each option by its own label", () => {
    render(
      <>
        <span id="kind-question">Kind</span>
        <Radio labelledBy="kind-question" value="slot" onValueChange={noop} options={OPTIONS} />
      </>,
    );

    expect(screen.getByRole("radio", { name: "slot" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "concrete" })).not.toBeChecked();
  });
});

describe("an interval named by an element the screen drew", () => {
  it("takes its name from that element and carries no string of its own", () => {
    render(
      <>
        <span id="bounds-question">Day bounds</span>
        <TimeRangeInput labelledBy="bounds-question" value={BOUNDS} onValueChange={noop} />
      </>,
    );

    const interval = screen.getByRole("group", { name: "Day bounds" });
    expect(interval).toHaveAttribute("aria-labelledby", "bounds-question");
    expect(interval).not.toHaveAttribute("aria-label");
  });

  /* THE ENDS ARE NAMED BY THE WORD BESIDE THEM rather than by the interval's, because there is no string here
   * to compose one from: the words belong to the element the screen drew, and re-saying them in hidden text
   * would be the second copy this shape exists to remove. The fieldset is what carries the interval, which is
   * what a group around two fields is for. */
  it("names each end by its own word, with the interval carried by the group", () => {
    render(
      <>
        <span id="bounds-question">Day bounds</span>
        <TimeRangeInput labelledBy="bounds-question" value={BOUNDS} onValueChange={noop} />
      </>,
    );

    expect(screen.getByLabelText("from")).toHaveValue("07:00");
    expect(screen.getByLabelText("to")).toHaveValue("22:00");
  });

  it("leaves the words written once, in the element the screen drew", () => {
    const { container } = render(
      <>
        <span id="bounds-question">Day bounds</span>
        <TimeRangeInput labelledBy="bounds-question" value={BOUNDS} onValueChange={noop} />
      </>,
    );

    expect(authoredNames(container, "Day bounds")).toEqual([{ source: "drawn text", by: "span" }]);
  });

  it("describes both ends by the message the form row owns", () => {
    render(
      <>
        <span id="bounds-question">Day bounds</span>
        <TimeRangeInput
          labelledBy="bounds-question"
          describedBy="bounds-hint"
          value={BOUNDS}
          onValueChange={noop}
        />
        <p id="bounds-hint">Wall time, in whichever zone is active on the day.</p>
      </>,
    );

    expect(screen.getByLabelText("from")).toHaveAccessibleDescription(
      "Wall time, in whichever zone is active on the day.",
    );
    expect(screen.getByLabelText("to")).toHaveAccessibleDescription(
      "Wall time, in whichever zone is active on the day.",
    );
  });
});

/* THE ADMITTED SIDE, AND WHAT ARMS THE READER. A control named by its own words is legitimate wherever the
 * screen does not draw the question, and both controls keep that form. The pair of cases below is also the
 * only thing standing between `authoredNames` and a reader blind to half of what it claims to read: a census
 * that ignored `aria-label` would report one copy for every shape, and every assertion above would still
 * pass. */
describe("a control named by its own words", () => {
  it("is named by them, and composes each end of an interval from them", () => {
    render(<TimeRangeInput label="Moved to" value={BOUNDS} onValueChange={noop} />);

    expect(screen.getByRole("group", { name: "Moved to" })).toBeInTheDocument();
    expect(screen.getByLabelText("Moved to, from")).toHaveValue("07:00");
    expect(screen.getByLabelText("Moved to, to")).toHaveValue("22:00");
  });

  it("authors the words twice where the screen draws the question as well", () => {
    const { container } = render(
      <>
        <p>Kind</p>
        <Radio label="Kind" value="slot" onValueChange={noop} options={OPTIONS} />
      </>,
    );

    expect(authoredNames(container, "Kind")).toEqual([
      { source: "drawn text", by: "p" },
      { source: "aria-label", by: "div[role=radiogroup].flex" },
    ]);
  });
});

describe("the compiler", () => {
  it("refuses a radio group named by neither a drawn element nor a string", () => {
    // @ts-expect-error a group with no name is announced by its role alone
    const { container } = render(<Radio value="slot" onValueChange={noop} options={OPTIONS} />);

    expect(container.querySelector("[role=radiogroup]")).not.toBeNull();
  });

  it("refuses a radio group named by both", () => {
    const named = (
      // @ts-expect-error two names for one control is two strings to keep in step
      <Radio
        label="Kind"
        labelledBy="kind-question"
        value="slot"
        onValueChange={noop}
        options={OPTIONS}
      />
    );
    const { container } = render(
      <>
        <span id="kind-question">Kind</span>
        {named}
      </>,
    );

    expect(container.querySelector("[role=radiogroup]")).not.toBeNull();
  });

  it("refuses an interval named by neither", () => {
    // @ts-expect-error a group with no name is announced by its role alone
    const { container } = render(<TimeRangeInput value={BOUNDS} onValueChange={noop} />);

    expect(container.querySelector("fieldset")).not.toBeNull();
  });

  it("refuses an interval named by both", () => {
    const named = (
      // @ts-expect-error two names for one control is two strings to keep in step
      <TimeRangeInput
        label="Day bounds"
        labelledBy="bounds-question"
        value={BOUNDS}
        onValueChange={noop}
      />
    );
    const { container } = render(
      <>
        <span id="bounds-question">Day bounds</span>
        {named}
      </>,
    );

    expect(container.querySelector("fieldset")).not.toBeNull();
  });
});
