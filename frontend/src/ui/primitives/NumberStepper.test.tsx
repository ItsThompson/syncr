/* The number stepper, and the one exception in the product.
 *
 * A plan value steps by --snap 15. The ledger's `actual-minutes` variant steps by 5 and is prefilled by its
 * caller with the planned duration, so the common correction is two keystrokes. These tests are what stop a
 * third step appearing without a decision: the step comes from a table keyed by the measure, and the buttons
 * announce the step they will apply. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { NumberStepper } from "./NumberStepper";

function renderStepper(props: Partial<Parameters<typeof NumberStepper>[0]> = {}) {
  const onValueChange = vi.fn<(next: number) => void>();
  render(
    <NumberStepper
      value={210}
      onValueChange={onValueChange}
      measure="duration"
      label="Estimate"
      {...props}
    />,
  );
  return { onValueChange };
}

describe("a duration stepper", () => {
  it("steps up by the quarter hour", async () => {
    const { onValueChange } = renderStepper();

    await userEvent.click(screen.getByRole("button", { name: "increase 15 minutes" }));

    expect(onValueChange).toHaveBeenCalledWith(225);
  });

  it("steps down by the quarter hour", async () => {
    const { onValueChange } = renderStepper();

    await userEvent.click(screen.getByRole("button", { name: "decrease 15 minutes" }));

    expect(onValueChange).toHaveBeenCalledWith(195);
  });

  it("announces the step it will apply rather than a generic increase", () => {
    renderStepper();

    expect(screen.getByRole("button", { name: "increase 15 minutes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "decrease 15 minutes" })).toBeInTheDocument();
  });

  it("tells the browser the same step, so its own arrow keys agree with the buttons", () => {
    renderStepper();

    expect(screen.getByRole("spinbutton")).toHaveAttribute("step", "15");
  });

  it("snaps a typed figure to the quarter hour on commit", async () => {
    const { onValueChange } = renderStepper({ value: 50 });

    await userEvent.click(screen.getByRole("spinbutton"));
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith(45);
  });

  it("holds the floor rather than stepping below it", async () => {
    const { onValueChange } = renderStepper({ value: 15, min: 15 });

    await userEvent.click(screen.getByRole("button", { name: "decrease 15 minutes" }));

    expect(onValueChange).toHaveBeenCalledWith(15);
  });

  it("holds the ceiling rather than stepping above it", async () => {
    const { onValueChange } = renderStepper({ value: 60, max: 60 });

    await userEvent.click(screen.getByRole("button", { name: "increase 15 minutes" }));

    expect(onValueChange).toHaveBeenCalledWith(60);
  });
});

/* THE ONE EXCEPTION. A recorded actual is a measurement rather than a placement, and nothing about a
 * measurement lands on a grid. */
describe("an actual-minutes stepper", () => {
  it("steps by five", async () => {
    const { onValueChange } = renderStepper({ measure: "actual-minutes", value: 45 });

    await userEvent.click(screen.getByRole("button", { name: "increase 5 minutes" }));

    expect(onValueChange).toHaveBeenCalledWith(50);
  });

  it("snaps a typed figure to five rather than to the quarter hour", async () => {
    const { onValueChange } = renderStepper({ measure: "actual-minutes", value: 52 });

    await userEvent.click(screen.getByRole("spinbutton"));
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith(50);
  });

  it("accepts the prefill it was given, so the common case is two keystrokes", () => {
    renderStepper({ measure: "actual-minutes", value: 30 });

    expect(screen.getByRole("spinbutton")).toHaveValue(30);
  });
});

describe("the stepper's own rendering", () => {
  it("renders the unit as prose beside the figure rather than inside it", () => {
    renderStepper({ unit: "min · 3h30m" });

    expect(screen.getByText("min · 3h30m")).toBeInTheDocument();
    expect(screen.getByRole("spinbutton")).toHaveValue(210);
  });

  it("disables the buttons with the field, so half a control cannot stay live", () => {
    renderStepper({ isDisabled: true });

    expect(screen.getByRole("spinbutton")).toBeDisabled();
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  });

  it("marks invalid with aria-invalid", () => {
    renderStepper({ isInvalid: true });

    expect(screen.getByRole("spinbutton")).toHaveAttribute("aria-invalid", "true");
  });

  it("sets its figure in tabular numerals and takes the figure width", () => {
    renderStepper();
    const classes = [...screen.getByRole("spinbutton").classList];

    expect(classes).toContain("control--figure");
    expect(classes).toContain("number-stepper__field");
  });

  it("removes the native spin buttons, so one field has one pair of controls", async () => {
    const css = await kitStylesheet("NumberStepper.css");

    expect(css).toContain("::-webkit-inner-spin-button");
    expect(css).toContain("appearance: none");
  });
});
