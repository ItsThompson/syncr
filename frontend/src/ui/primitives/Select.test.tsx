/* The select, and the two claims the ticket makes about it.
 *
 * THE NATIVE ARROW IS REPLACED BY A TYPOGRAPHIC MARK so the box stays square: Radix's trigger is a button, so
 * no platform ever draws the arrow in a well with its own corner radius.
 * data-highlighted MAPS TO FOCUS AND NOTHING ELSE, which is the shared row treatment in `states.css`. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { Select } from "./Select";

const OPTIONS = [
  { value: "career", label: "Career" },
  { value: "study", label: "Study" },
  { value: "research", label: "Research", isDisabled: true },
];

function renderSelect(props: Partial<Parameters<typeof Select>[0]> = {}) {
  const onValueChange = vi.fn<(next: string) => void>();
  const result = render(
    <Select
      value="career"
      onValueChange={onValueChange}
      options={OPTIONS}
      label="Area"
      {...props}
    />,
  );
  return { onValueChange, ...result };
}

describe("Select", () => {
  it("renders a button rather than a native select, so the box is this system's", () => {
    renderSelect();

    expect(screen.getByRole("combobox", { name: "Area" }).tagName).toBe("BUTTON");
  });

  it("shows the chosen option's label", () => {
    renderSelect();

    expect(screen.getByRole("combobox")).toHaveTextContent("Career");
  });

  it("shows the placeholder while nothing is chosen", () => {
    renderSelect({ value: "", placeholder: "Choose an Area" });

    expect(screen.getByRole("combobox")).toHaveTextContent("Choose an Area");
  });

  it("carries the typographic mark from the glyph table, not a native arrow", () => {
    const { container } = renderSelect();
    const mark = container.querySelector(".glyph--triangle-down");

    expect(mark).not.toBeNull();
    expect(mark).toHaveAttribute("aria-hidden", "true");
  });

  it("takes the control's own border, so it reads as a field", () => {
    renderSelect();

    expect([...screen.getByRole("combobox").classList]).toContain("control");
  });

  it("marks invalid with aria-invalid", () => {
    renderSelect({ isInvalid: true });

    expect(screen.getByRole("combobox")).toHaveAttribute("aria-invalid", "true");
  });

  it("is disabled as a native control", () => {
    renderSelect({ isDisabled: true });

    expect(screen.getByRole("combobox")).toBeDisabled();
  });

  it("opens on a click and lists every option", async () => {
    renderSelect();

    await userEvent.click(screen.getByRole("combobox"));

    expect(screen.getByRole("option", { name: "Career" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Study" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Research" })).toBeInTheDocument();
  });

  it("hands the caller the chosen value", async () => {
    const { onValueChange } = renderSelect();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Study" }));

    expect(onValueChange).toHaveBeenCalledWith("study");
  });

  it("refuses a disabled option rather than styling it and accepting it", async () => {
    const { onValueChange } = renderSelect();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Research" }));

    expect(onValueChange).not.toHaveBeenCalled();
  });

  it("gives every row the kit's shared row treatment rather than its own", async () => {
    renderSelect();

    await userEvent.click(screen.getByRole("combobox"));

    for (const option of screen.getAllByRole("option")) {
      expect([...option.classList]).toContain("state-row");
    }
  });

  it("marks the chosen row with a glyph, which survives forced colors", async () => {
    const { container } = renderSelect();

    await userEvent.click(screen.getByRole("combobox"));

    expect(container.ownerDocument.querySelector(".glyph--check")).not.toBeNull();
  });
});

describe("the select's stylesheet", () => {
  it("pitches a row at the row height the rest of the product uses", async () => {
    expect(await kitStylesheet("Select.css")).toContain("height: var(--h-row)");
  });

  it("gives a disabled option a dashed rule as well as muted text", async () => {
    const css = await kitStylesheet("Select.css");
    const rule = /\.select__item\[data-disabled\]\s*\{([^}]*)\}/.exec(css);

    expect(rule?.[1]).toContain("dashed");
    expect(rule?.[1]).toContain("var(--text-muted)");
  });

  it("declares no ring of its own: the cursor's ring is the kit's", async () => {
    const declarations = (await kitStylesheet("Select.css")).replace(/\/\*[\s\S]*?\*\//g, "");

    expect(declarations).not.toContain("outline");
  });
});
