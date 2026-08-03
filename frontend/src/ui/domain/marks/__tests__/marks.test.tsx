/* The three marks, and the two rules that are the reason they are components at all.
 *
 * An Area chip may not appear without its Area's name, and a key hint has exactly one form. Both are stated as
 * rules in the design language, and both are enforced here by something other than review: the name is a
 * required prop the typecheck refuses to omit, and the hint's brackets come from the kit's own glyph table. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { AreaChip } from "../AreaChip";
import { GlyphSlot } from "../GlyphSlot";
import { KeyHint } from "../KeyHint";
import { glyphSlotOccupant } from "../occupant";
import { AREA_PIGMENTS, areaPigment } from "../pigment";

const marksStylesheet = () => kitStylesheet("marks/marks.css", domainDir);

describe("an Area chip", () => {
  it("renders the Area's name beside the chip, which is what identifies the Area", () => {
    render(<AreaChip name="Career" pigment="03" />);

    expect(screen.getByText("Career")).toBeInTheDocument();
  });

  it("takes its pigment from the ramp step, written where the markup scan can read it", () => {
    const { container } = render(<AreaChip name="Career" pigment="03" />);

    expect(container.querySelector(".area-chip")).toHaveClass("bg-area-03");
  });

  it("hides the chip from a screen reader, so the Area is announced once", () => {
    const { container } = render(<AreaChip name="Career" pigment="03" />);

    expect(container.querySelector(".area-chip")).toHaveAttribute("aria-hidden", "true");
  });

  /* THE NAME CANNOT BE OMITTED, and this is the assertion for it: `tsc --noEmit` runs over `src`, so a
   * `@ts-expect-error` that stops erroring fails the typecheck. A rendered test could only show that a chip
   * without a name draws nothing useful; this shows it does not compile. */
  it("does not compile without one", () => {
    // @ts-expect-error a chip without its Area's name encodes a category in colour alone
    const withoutName = <AreaChip pigment="03" />;

    expect(withoutName).not.toBeNull();
  });

  it("maps every assigned index onto a ramp step, and wraps past the sealed twelve", () => {
    expect(AREA_PIGMENTS).toHaveLength(12);
    expect(areaPigment(0)).toBe("01");
    expect(areaPigment(11)).toBe("12");
    expect(areaPigment(12)).toBe("01");
    expect(areaPigment(-1)).toBe("12");
  });

  /* THE TWO GEOMETRY FACTS THE CRITERION NAMES, read from the stylesheet because jsdom applies none. Nothing else
   * fails if either changes: a chip at 14px still renders, and a square one still renders. */
  it("is at most 10px and circular, which is one of the four legal circles", async () => {
    const css = await marksStylesheet();
    const chip = /\.area-chip\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";

    expect(chip).toContain("width: 10px");
    expect(chip).toContain("height: 10px");
    expect(chip).toContain("border-radius: 50%");
  });
});

describe("a key hint", () => {
  it("is keyboard input a screen reader announces as such", () => {
    render(<KeyHint keys="j" />);

    expect(screen.getByText("j").tagName).toBe("KBD");
  });

  it("draws its brackets from the glyph table's pair rather than from two literals", async () => {
    const css = await marksStylesheet();

    expect(css).toContain("content: var(--glyph-bracket-open)");
    expect(css).toContain("content: var(--glyph-bracket-close)");
  });

  it("has no bordered key cap, in any spelling, because there is one form", async () => {
    const css = await marksStylesheet();
    const hint = /\.key-hint\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";

    expect(hint).not.toContain("border");
    expect(hint).not.toContain("background");
  });
});

describe("the glyph slot", () => {
  it("draws the origin mark when nothing louder claims the slot", () => {
    const { container } = render(<GlyphSlot origin="anchor" />);

    expect(container.querySelector(".glyph")).toHaveClass("glyph--origin-anchor");
  });

  it("yields the slot to the pin, which is the user's own edit", () => {
    const { container } = render(<GlyphSlot origin="anchor" isPinned />);

    expect(container.querySelector(".glyph")).toHaveClass("glyph--pinned");
  });

  it("carries the count beside its marker, in tabular figures", () => {
    render(<GlyphSlot overlapCount={4} />);

    expect(screen.getByText("4")).toHaveClass("glyph--overlap");
  });

  it("draws nothing at all when no occupant claims it", () => {
    const { container } = render(<GlyphSlot />);

    expect(container.firstElementChild).toBeNull();
  });

  it("hides the mark from a screen reader, because the block already says what it is", () => {
    const { container } = render(<GlyphSlot isPinned />);

    expect(container.querySelector(".glyph")).toHaveAttribute("aria-hidden", "true");
  });

  it.each([
    [
      { isPinned: true, overlapCount: 5, isProposalSource: true, origin: "task" as const },
      "pinned",
    ],
    [{ overlapCount: 5, isProposalSource: true, origin: "task" as const }, "overlap"],
    [{ isProposalSource: true, origin: "task" as const }, "proposal-source"],
    [{ origin: "task" as const }, "task"],
    [{}, null],
    /* A count of one or none is not a claim on the slot: the marker appears at depth 4 and above, so a caller
     * passing a count that low would otherwise put the digit where the origin mark belongs. */
    [{ overlapCount: 0, origin: "task" as const }, "task"],
    [{ overlapCount: 1, isProposalSource: true }, "proposal-source"],
  ])("settles the precedence: %o wins as %s", (claim, occupant) => {
    expect(glyphSlotOccupant(claim)).toBe(occupant);
  });
});
