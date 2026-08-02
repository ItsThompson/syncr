/* The interval control: two clock times, one snap, prefilled from a planned interval.
 *
 * ORDER IS NOT THIS CONTROL'S BUSINESS, and the test for that is deliberate rather than an omission. An
 * off-plan period runs from Friday afternoon to Monday morning, so an end before its start is a real interval;
 * only the caller knows which day each end belongs to. A control that refused it would forbid the case the
 * product exists to handle. */

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TimeRangeInput, type TimeRange } from "./TimeRangeInput";

function renderRange(start = "13:00", end = "14:30") {
  const onValueChange = vi.fn<(next: TimeRange) => void>();
  const result = render(
    <TimeRangeInput value={{ start, end }} onValueChange={onValueChange} label="Moved to" />,
  );
  return { onValueChange, ...result };
}

describe("TimeRangeInput", () => {
  it("prefills both ends from the interval it was given", () => {
    renderRange();

    expect(screen.getByLabelText("Moved to, from")).toHaveValue("13:00");
    expect(screen.getByLabelText("Moved to, to")).toHaveValue("14:30");
  });

  it("names the interval once and each end from it", () => {
    renderRange();

    expect(screen.getByRole("group", { name: "Moved to" })).toBeInTheDocument();
  });

  it("hands back the whole interval when one end changes", async () => {
    const { onValueChange } = renderRange();
    const start = screen.getByLabelText("Moved to, from");

    start.focus();
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith({ start: "13:00", end: "14:30" });
  });

  it("hands back the whole interval when the end changes", async () => {
    const { onValueChange } = renderRange();
    const end = screen.getByLabelText("Moved to, to");

    fireEvent.change(end, { target: { value: "15:00" } });

    expect(onValueChange).toHaveBeenLastCalledWith({ start: "13:00", end: "15:00" });
  });

  it("snaps each end with the same snap the single control uses", async () => {
    const { onValueChange } = renderRange("13:07", "14:30");
    const start = screen.getByLabelText("Moved to, from");

    start.focus();
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith({ start: "13:00", end: "14:30" });
  });

  it("accepts an end before its start, because an interval may cross midnight", () => {
    renderRange("14:00", "09:00");

    expect(screen.getByLabelText("Moved to, from")).toHaveValue("14:00");
    expect(screen.getByLabelText("Moved to, to")).toHaveValue("09:00");
    expect(screen.getByLabelText("Moved to, to")).not.toHaveAttribute("aria-invalid");
  });

  it("marks both ends invalid when the caller says the interval is", () => {
    const onValueChange = vi.fn<(next: TimeRange) => void>();
    render(
      <TimeRangeInput
        value={{ start: "13:00", end: "14:30" }}
        onValueChange={onValueChange}
        label="Moved to"
        isInvalid
      />,
    );

    expect(screen.getByLabelText("Moved to, from")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Moved to, to")).toHaveAttribute("aria-invalid", "true");
  });
});
