/* The time controls: one clock time, and an interval made of two.
 *
 * The snap is 15 minutes and it is applied on commit rather than on every keystroke, because snapping while a
 * reader types turns 13:4 into 13:00 before they reach the second digit. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TimeInput } from "./TimeInput";

function renderTime(props: Partial<Parameters<typeof TimeInput>[0]> = {}) {
  const onValueChange = vi.fn<(next: string) => void>();
  const result = render(
    <TimeInput value="09:00" onValueChange={onValueChange} label="Start" {...props} />,
  );
  return { onValueChange, ...result };
}

function timeField(container: HTMLElement): HTMLInputElement {
  const field = container.querySelector("input[type='time']");
  if (field === null) throw new Error("no time field rendered");
  return field as HTMLInputElement;
}

describe("TimeInput", () => {
  it("is a native time field, so the platform's own keyboard works", () => {
    const { container } = renderTime();

    expect(timeField(container)).toHaveValue("09:00");
  });

  it("tells the browser the snap, so its arrow keys land on a quarter hour", () => {
    const { container } = renderTime();

    expect(timeField(container)).toHaveAttribute("step", "900");
  });

  it("snaps to the nearest quarter hour on commit", async () => {
    const { container, onValueChange } = renderTime({ value: "09:07" });

    timeField(container).focus();
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith("09:00");
  });

  it("snaps upward from the midpoint, so a reader who types 09:08 gets 09:15", async () => {
    const { container, onValueChange } = renderTime({ value: "09:08" });

    timeField(container).focus();
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith("09:15");
  });

  it("does not roll the end of the day into the next one", async () => {
    const { container, onValueChange } = renderTime({ value: "23:53" });

    timeField(container).focus();
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith("23:45");
  });

  it("leaves a value it cannot read alone rather than correcting it", async () => {
    const { container, onValueChange } = renderTime({ value: "" });

    timeField(container).focus();
    await userEvent.tab();

    expect(onValueChange).toHaveBeenLastCalledWith("");
  });

  it("marks invalid with aria-invalid", () => {
    const { container } = renderTime({ isInvalid: true });

    expect(timeField(container)).toHaveAttribute("aria-invalid", "true");
  });

  it("takes the figure width, because a clock time is a figure", () => {
    const { container } = renderTime();

    expect([...timeField(container).classList]).toContain("control--figure");
  });

  it("is named for a screen reader even with no visible label", () => {
    renderTime();

    expect(screen.getByLabelText("Start")).toBeInTheDocument();
  });
});
