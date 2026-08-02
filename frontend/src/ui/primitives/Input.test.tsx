/* The field family: the text field, the figure variant, and the states a form drives.
 *
 * The border's contrast ledger is in `Input.contrast.test.ts`, computed from the token files. This file is
 * about behaviour and about the attributes a form row and a screen reader both read. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { appliedDeclarations } from "../../testing/visualState";
import { Input } from "./Input";

function renderInput(props: Partial<Parameters<typeof Input>[0]> = {}) {
  const onValueChange = vi.fn<(next: string) => void>();
  const result = render(
    <Input
      value="Prep for Kontron Interview"
      onValueChange={onValueChange}
      label="Task"
      {...props}
    />,
  );
  return { onValueChange, ...result };
}

describe("Input", () => {
  it("hands the caller the value rather than the event", async () => {
    const { onValueChange } = renderInput({ value: "" });

    await userEvent.type(screen.getByRole("textbox"), "a");

    expect(onValueChange).toHaveBeenCalledWith("a");
  });

  it("is a text field, so a browser offers no widget of its own", () => {
    renderInput();

    expect(screen.getByRole("textbox")).toHaveAttribute("type", "text");
  });

  it("marks invalid with aria-invalid, so the state and the styling hook are one attribute", () => {
    renderInput({ isInvalid: true });

    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
  });

  it("leaves aria-invalid off a valid field rather than setting it false", () => {
    renderInput();

    expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-invalid");
  });

  it("points at the hint or error the form row owns", () => {
    renderInput({ describedBy: "estimate-hint" });

    expect(screen.getByRole("textbox")).toHaveAttribute("aria-describedby", "estimate-hint");
  });

  it("is disabled as a native control, so the tab order skips it", () => {
    renderInput({ isDisabled: true });

    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("sets the figure variant apart, because a number is compared down a column", () => {
    const { container } = renderInput({ measure: "figure" });
    const field = container.querySelector("input");
    if (field === null) throw new Error("no field rendered");

    expect([...field.classList]).toContain("control--figure");
  });

  it("forwards a ref, so a form can move focus to the first invalid field", () => {
    let node: HTMLInputElement | null = null;
    renderInput({
      ref: (element) => {
        node = element;
      },
    });

    expect(node).toBeInstanceOf(HTMLInputElement);
  });
});

describe("the field's own stylesheet", () => {
  it("gives an invalid field the 3px oxide rule and leaves its fill alone", async () => {
    const { container } = renderInput({ isInvalid: true });
    const field = container.querySelector("input");
    if (field === null) throw new Error("no field rendered");

    const applied = appliedDeclarations({
      element: field,
      css: await kitStylesheet("control.css"),
    });

    expect(applied).toContain("border-left-width: var(--state-conflict-border)");
    expect(applied).toContain("border-left-color: var(--state-conflict-color)");
    // The fill and the text never change colour: a fill is not a signal channel.
    expect(applied).toContain("background: var(--paper-raised)");
    expect(applied).toContain("color: var(--ink)");
  });

  it("gives a disabled field the dashed border, which is what disabled means here", async () => {
    const { container } = renderInput({ isDisabled: true });
    const field = container.querySelector("input");
    if (field === null) throw new Error("no field rendered");

    const applied = appliedDeclarations({
      element: field,
      css: await kitStylesheet("control.css"),
    });

    expect(applied).toContain("border-style: dashed");
  });

  it("suppresses the native picker indicator, so the box stays square on every platform", async () => {
    expect(await kitStylesheet("control.css")).toContain("::-webkit-calendar-picker-indicator");
  });

  it("sets its figures in tabular numerals, which the mono gives for free", async () => {
    expect(await kitStylesheet("control.css")).toContain("font-variant-numeric: tabular-nums");
  });
});
