/* The accordion, and the disclosure mark the design language names by hand.
 *
 * `[ + ]` and `[ - ]` come from the glyph table, keyed on Radix's `data-state` on the trigger. That pair is the
 * kit's assignment of the glyph-slot channel, and the mark is generated content: `aria-expanded` is what a
 * screen reader reads, so the glyph is hidden from it. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

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

/* EXPANDING ANCHORS THE SCROLL POSITION TO THE TOGGLED SECTION, which is the rendering discipline's answer to a
 * disclosure that opens in one frame: everything below it moves at once, and a section below the fold would put
 * different content under the reader's eyes than the row they touched.
 *
 * jsdom HAS NO LAYOUT, so the two measurements are supplied: `getBoundingClientRect` is stubbed to answer the
 * position the trigger would be at before and after the panel opened, which is the shape a browser produces. What
 * is under test is the arithmetic and the wiring, that the element measured is the one the reader activated and
 * that the correction is instant; `e2e/tests/s24-accessibility.spec.ts` measures the real thing in Chrome. */
/* The trigger's position, as the test moves it. A SEQUENCE OF READS WOULD NOT DO: Radix measures during a click
 * too, so a stub answering "the first read, then the second" hands the panel's own measurement the position that
 * belonged to the anchor. The position is therefore a value the test sets between the phases. */
function measuring(top: () => number): () => void {
  const original = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function measured(this: Element): DOMRect {
    return new DOMRect(0, top(), 100, 26);
  };
  return () => {
    Element.prototype.getBoundingClientRect = original;
  };
}

describe("expanding a section", () => {
  function reopened(
    rerender: (element: ReactElement) => void,
    onOpenValuesChange: (next: readonly string[]) => void,
    open: readonly string[],
  ): void {
    rerender(
      <Accordion
        sections={SECTIONS}
        openValues={open}
        onOpenValuesChange={onOpenValuesChange}
        canExpandMany
      />,
    );
  }

  it("scrolls by exactly what the toggled trigger moved, so the row stays where the reader left it", async () => {
    const scrollBy = vi.spyOn(window, "scrollBy").mockImplementation(() => {});
    let top = 100;
    const restore = measuring(() => top);
    try {
      const { onOpenValuesChange, rerender } = renderAccordion([], true);
      await userEvent.click(screen.getByRole("button", { name: /Routines/ }));
      expect(onOpenValuesChange).toHaveBeenCalled();

      /* The section above it opened, so this trigger is 180px further down the page than it was. */
      top = 280;
      reopened(rerender, onOpenValuesChange, ["routines"]);

      expect(scrollBy).toHaveBeenCalledWith(0, 180);
    } finally {
      restore();
      scrollBy.mockRestore();
    }
  });

  it("scrolls by nothing when the toggled trigger did not move, which is a section above the fold", async () => {
    const scrollBy = vi.spyOn(window, "scrollBy").mockImplementation(() => {});
    const restore = measuring(() => 100);
    try {
      const { onOpenValuesChange, rerender } = renderAccordion([], true);
      await userEvent.click(screen.getByRole("button", { name: /Day types/ }));

      reopened(rerender, onOpenValuesChange, ["day-types"]);

      expect(scrollBy).not.toHaveBeenCalled();
    } finally {
      restore();
      scrollBy.mockRestore();
    }
  });

  it("anchors nothing when what is open changed without a trigger being touched", () => {
    const scrollBy = vi.spyOn(window, "scrollBy").mockImplementation(() => {});
    let top = 100;
    const restore = measuring(() => top);
    try {
      const { onOpenValuesChange, rerender } = renderAccordion([], true);

      /* A screen opening a section itself, from a URL or a keyboard chord: nothing was held, so nothing is
       * restored. Correcting the scroll here would move the page under a reader who never touched it. */
      top = 400;
      reopened(rerender, onOpenValuesChange, ["anchors"]);

      expect(scrollBy).not.toHaveBeenCalled();
    } finally {
      restore();
      scrollBy.mockRestore();
    }
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
