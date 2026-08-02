/* The accordion, and the disclosure mark the design language names by hand.
 *
 * `[ + ]` and `[ - ]` come from the glyph table, keyed on Radix's `data-state` on the trigger. That pair is the
 * kit's assignment of the glyph-slot channel, and the mark is generated content: `aria-expanded` is what a
 * screen reader reads, so the glyph is hidden from it. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { Accordion } from "./Accordion";

const SECTIONS = [
  { value: "day-types", label: "Day types", count: 4, content: <p>Four day types</p> },
  { value: "routines", label: "Routines", count: 0, content: <p>Three routines</p> },
  { value: "anchors", label: "Anchor types", content: <p>Two anchor types</p> },
];

function renderAccordion(open: readonly string[] = [], canExpandMany = false) {
  const onOpenValuesChange = vi.fn<(next: readonly string[]) => void>();
  const result = render(
    <Accordion
      sections={SECTIONS}
      openValues={open}
      onOpenValuesChange={onOpenValuesChange}
      canExpandMany={canExpandMany}
    />,
  );
  return { onOpenValuesChange, ...result };
}

describe("Accordion", () => {
  it("renders one trigger per section", () => {
    renderAccordion();

    expect(screen.getAllByRole("button")).toHaveLength(SECTIONS.length);
  });

  it("announces the closed state on the trigger rather than in a class", () => {
    renderAccordion();

    expect(screen.getByRole("button", { name: /Day types/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("shows the open section's body and no other", () => {
    renderAccordion(["day-types"]);

    expect(screen.getByText("Four day types")).toBeInTheDocument();
    expect(screen.queryByText("Three routines")).toBeNull();
  });

  it("hands the caller the section that was opened", async () => {
    const { onOpenValuesChange } = renderAccordion();

    await userEvent.click(screen.getByRole("button", { name: /Routines/ }));

    expect(onOpenValuesChange).toHaveBeenCalledWith(["routines"]);
  });

  it("closes an open section, so the disclosure is a toggle", async () => {
    const { onOpenValuesChange } = renderAccordion(["routines"]);

    await userEvent.click(screen.getByRole("button", { name: /Routines/ }));

    expect(onOpenValuesChange).toHaveBeenCalledWith([]);
  });

  it("holds one section open at a time unless the caller says otherwise", async () => {
    const { onOpenValuesChange } = renderAccordion(["day-types"]);

    await userEvent.click(screen.getByRole("button", { name: /Routines/ }));

    expect(onOpenValuesChange).toHaveBeenCalledWith(["routines"]);
  });

  it("holds several open where canExpandMany is set", async () => {
    const { onOpenValuesChange } = renderAccordion(["day-types"], true);

    await userEvent.click(screen.getByRole("button", { name: /Routines/ }));

    expect(onOpenValuesChange).toHaveBeenCalledWith(["day-types", "routines"]);
  });

  it("carries the disclosure slot on every trigger, hidden from a screen reader", () => {
    const { container } = renderAccordion();
    const marks = container.querySelectorAll(".glyph--disclosure");

    expect(marks).toHaveLength(SECTIONS.length);
    for (const mark of marks) expect(mark).toHaveAttribute("aria-hidden", "true");
  });

  it("shows a count of zero rather than hiding it", () => {
    renderAccordion();

    expect(screen.getByRole("button", { name: /Routines/ })).toHaveTextContent("0");
  });
});

/* THE MARKS THEMSELVES, read from the table. A component that named `[ + ]` inline would put a literal where no
 * other component could see it, which is what the glyph table exists to prevent. */
describe("the disclosure mark", () => {
  it("is the plus mark when the section is closed", async () => {
    const css = await kitStylesheet("glyphs.css");
    const closed = /\.glyph--disclosure\s*\{([^}]*)\}/.exec(css);

    expect(closed?.[1]).toContain("var(--glyph-plus)");
  });

  it("is the minus mark when the section is open, keyed on the trigger's own state", async () => {
    const css = await kitStylesheet("glyphs.css");
    const open = /\[data-state="open"\]\s+\.glyph--disclosure\s*\{([^}]*)\}/.exec(css);

    expect(open?.[1]).toContain("var(--glyph-minus)");
  });

  it("sits inside the brackets the key hints use, so there is one bracketed form", () => {
    const { container } = renderAccordion();
    const mark = container.querySelector(".glyph--disclosure");

    expect([...(mark?.classList ?? [])]).toContain("glyph--bracketed");
  });
});
