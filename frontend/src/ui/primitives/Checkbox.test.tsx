/* The checkbox, with three states rather than two.
 *
 * The mark is a glyph, so the state survives forced colors: a fill is dropped there and text is not. The box is
 * the button and the text beside it is a real label pointing at it, which is what keeps the focus ring on the
 * control and makes clicking the words toggle the box with no handler. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { Checkbox } from "./Checkbox";
import type { CheckboxState } from "./Checkbox";

function renderCheckbox(state: CheckboxState = "unchecked") {
  const onStateChange = vi.fn<(next: CheckboxState) => void>();
  const result = render(
    <Checkbox state={state} onStateChange={onStateChange}>
      Splittable
    </Checkbox>,
  );
  return { onStateChange, ...result };
}

describe("Checkbox", () => {
  it("takes its accessible name from the label beside it", () => {
    renderCheckbox();

    expect(screen.getByRole("checkbox", { name: "Splittable" })).toBeInTheDocument();
  });

  it.each([
    ["checked", "true"],
    ["unchecked", "false"],
    ["indeterminate", "mixed"],
  ] as const)("announces %s as aria-checked %s", (state, announced) => {
    renderCheckbox(state);

    expect(screen.getByRole("checkbox")).toHaveAttribute("aria-checked", announced);
  });

  it("hands back the state as one of the three words rather than a boolean", async () => {
    const { onStateChange } = renderCheckbox("unchecked");

    await userEvent.click(screen.getByRole("checkbox"));

    expect(onStateChange).toHaveBeenCalledWith("checked");
  });

  it("toggles from the label, because a button is a labelable element", async () => {
    const { onStateChange } = renderCheckbox("unchecked");

    await userEvent.click(screen.getByText("Splittable"));

    expect(onStateChange).toHaveBeenCalledWith("checked");
  });

  it("draws the tick as a glyph, so the state survives forced colors", () => {
    const { container } = renderCheckbox("checked");
    const mark = container.querySelector(".glyph--check");

    expect(mark).not.toBeNull();
    expect(mark).toHaveAttribute("aria-hidden", "true");
  });

  it("draws the indeterminate state as the minus mark rather than a tick", () => {
    const { container } = renderCheckbox("indeterminate");

    expect(container.querySelector(".glyph--minus")).not.toBeNull();
    expect(container.querySelector(".glyph--check")).toBeNull();
  });

  it("draws no mark at all when unchecked", () => {
    const { container } = renderCheckbox("unchecked");

    expect(container.querySelector(".glyph")).toBeNull();
  });

  it("is disabled as a native control", () => {
    const onStateChange = vi.fn<(next: CheckboxState) => void>();
    render(
      <Checkbox state="unchecked" onStateChange={onStateChange} isDisabled>
        Infer shadows automatically
      </Checkbox>,
    );

    expect(screen.getByRole("checkbox")).toBeDisabled();
  });
});

describe("the toggle stylesheet", () => {
  it("draws the box at the small control height, not a touch target", async () => {
    expect(await kitStylesheet("toggle.css")).toContain("min-height: var(--h-control-sm)");
  });

  it("keeps the ring on the control by declaring none of its own", async () => {
    const declarations = (await kitStylesheet("toggle.css")).replace(/\/\*[\s\S]*?\*\//g, "");

    expect(declarations).not.toContain("outline");
  });
});
