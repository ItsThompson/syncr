/* The radio group. One radio on its own means nothing, so the primitive is the group.
 *
 * The dot is one of the four legal circles, and it is an element rather than a glyph because a filled circle at
 * 6px is geometry: a character's weight and baseline vary by font. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { Radio } from "./Radio";

const OPTIONS = [
  { value: "forgive", label: "forgive" },
  { value: "debt", label: "debt" },
  { value: "decay", label: "decay · unfitted", isDisabled: true },
];

function renderRadio(value = "forgive") {
  const onValueChange = vi.fn<(next: string) => void>();
  const result = render(
    <Radio value={value} onValueChange={onValueChange} options={OPTIONS} label="Miss policy" />,
  );
  return { onValueChange, ...result };
}

describe("Radio", () => {
  it("names the group, which is what a screen reader reads before the chosen option", () => {
    renderRadio();

    expect(screen.getByRole("radiogroup", { name: "Miss policy" })).toBeInTheDocument();
  });

  it("renders one radio per option", () => {
    renderRadio();

    expect(screen.getAllByRole("radio")).toHaveLength(OPTIONS.length);
  });

  it("marks the chosen option and no other", () => {
    renderRadio();

    expect(screen.getByRole("radio", { name: "forgive" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "debt" })).not.toBeChecked();
  });

  it("hands the caller the chosen value", async () => {
    const { onValueChange } = renderRadio();

    await userEvent.click(screen.getByRole("radio", { name: "debt" }));

    expect(onValueChange).toHaveBeenCalledWith("debt");
  });

  it("chooses from the label, because a button is a labelable element", async () => {
    const { onValueChange } = renderRadio();

    await userEvent.click(screen.getByText("debt"));

    expect(onValueChange).toHaveBeenCalledWith("debt");
  });

  it("takes one tab stop for the whole group, which is what the arrow keys are for", async () => {
    renderRadio();

    await userEvent.tab();

    expect(screen.getByRole("radio", { name: "forgive" })).toHaveFocus();

    await userEvent.tab();

    expect(screen.getByRole("radio", { name: "debt" })).not.toHaveFocus();
  });

  /* Radix owns the roving focus, so the arrow key moves between options rather than out of the group. The
   * SELECTION that follows the move happens on focus in a real browser and does not fire in jsdom, where
   * Radix's arrow-key detection reads a document-level key sequence: the movement is what is assertable here,
   * and the E2E suite drives the whole gesture in a browser. */
  it("moves focus to the next option with an arrow key rather than out of the group", async () => {
    renderRadio();

    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");

    expect(screen.getByRole("radio", { name: "debt" })).toHaveFocus();
  });

  it("disables an option without disabling the group", () => {
    renderRadio();

    expect(screen.getByRole("radio", { name: "decay · unfitted" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "forgive" })).toBeEnabled();
  });

  it("draws the dot as an element on the closed circle allowlist", async () => {
    const { container } = renderRadio();
    const dot = container.querySelector(".toggle__dot");
    const css = await kitStylesheet("toggle.css");

    expect(dot).not.toBeNull();
    expect(css).toContain("border-radius: 50%");
  });
});
