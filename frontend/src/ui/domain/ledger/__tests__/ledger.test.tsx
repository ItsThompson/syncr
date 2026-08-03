/* THE LEDGER ROW, AND THE TWO THINGS IT REFUSES TO DECIDE.
 *
 * It does not format an instant and it does not wire an outcome. Both arrive from the screen that owns them: how an
 * interval reads depends on the reader's zone, and skip, partial and moved are mutations. What the row owns is that
 * the duration is tabular and right-aligned, that the Area is named beside its chip, and that the controls land in a
 * slot at a fixed offset. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "../../../primitives";
import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { GlyphSlot } from "../../marks";
import { LedgerRow } from "../LedgerRow";

const stylesheet = () => kitStylesheet("ledger/ledger.css", domainDir);

describe("a ledger row", () => {
  it("renders the time range, the duration and the title", () => {
    render(<LedgerRow timeRange="13:30-17:00" duration="3h 30m" title="Leetcode · DP" />);

    expect(screen.getByText("13:30-17:00")).toBeInTheDocument();
    expect(screen.getByText("3h 30m")).toBeInTheDocument();
    expect(screen.getByText("Leetcode · DP")).toBeInTheDocument();
  });

  it("names the Area beside its chip, because a chip alone encodes a category in colour", () => {
    const { container } = render(
      <LedgerRow
        timeRange="13:30-17:00"
        duration="3h 30m"
        title="Leetcode · DP"
        area={{ name: "Career", pigment: "01" }}
      />,
    );

    expect(screen.getByText("Career")).toBeInTheDocument();
    expect(container.querySelector(".area-chip")).toHaveClass("bg-area-01");
  });

  it("leaves the Area column empty for a routine, which carries no Area at all", () => {
    const { container } = render(
      <LedgerRow timeRange="05:15-05:30" duration="15m" title="Wake up" />,
    );

    expect(container.querySelector(".area-chip")).toBeNull();
    expect(container.querySelector(".ledger__area")).toBeEmptyDOMElement();
  });

  it("reserves the adornment column whether or not it holds a mark", () => {
    const withoutMark = render(<LedgerRow timeRange="18:00-19:00" duration="1h" title="Dinner" />);
    expect(withoutMark.container.querySelector(".gutter")).toBeEmptyDOMElement();
    withoutMark.unmount();

    const withMark = render(
      <LedgerRow
        timeRange="18:00-19:00"
        duration="1h"
        title="Dinner"
        mark={<GlyphSlot isPinned />}
      />,
    );
    expect(withMark.container.querySelector(".gutter .glyph--pinned")).not.toBeNull();
  });

  it("takes the outcome controls as children, which the screen that owns the mutation wires", () => {
    render(
      <LedgerRow timeRange="10:00-10:30" duration="30m" title="Clean">
        <Button rank="quiet" size="sm">
          skip
        </Button>
      </LedgerRow>,
    );

    expect(screen.getByRole("button", { name: "skip" })).toBeInTheDocument();
  });

  it("hovers on the kit's one fill, through the row states rather than its own rule", () => {
    const { container } = render(
      <LedgerRow timeRange="10:00-10:30" duration="30m" title="Clean" />,
    );

    expect(container.firstElementChild).toHaveClass("state-row");
  });
});

describe("the duration column", () => {
  it("is right-aligned and tabular, because a reader compares durations down the ledger", async () => {
    const css = await stylesheet();

    expect(/\.ledger__duration\s*\{[^}]*text-align:\s*right/.test(css)).toBe(true);
    expect(/font-variant-numeric:\s*tabular-nums/.test(css)).toBe(true);
  });
});
