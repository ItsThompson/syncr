/* WHAT THE COMPILER REFUSES, AND WHAT THE COMPONENT IGNORES.
 *
 * Two of this family's rules are stronger as types than as review notes: a deviation row carries no Area ink
 * anywhere, and a legend chip is never shown without the Area's name. Both are enforced by the typecheck, so the
 * cases below are `@ts-expect-error` directives rather than assertions: `tsc --noEmit` runs over `src`, so a
 * directive that STOPS erroring fails the typecheck and neither rule can be relaxed quietly.
 *
 * THE SECOND HALF IS WHAT A HOSTILE CALLER GETS. A structural type does not refuse an object that merely happens
 * to carry a pigment, so the last test hands one in through a variable, which is the shape that skips the excess
 * property check, and asserts nothing Area-inked reaches the DOM. Rejected AND ignored. */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { AreaLegend } from "../AreaLegend";
import { DeviationBar } from "../DeviationBar";
import { MaturityMeter } from "../MaturityMeter";
import { PieChart } from "../PieChart";
import type { AreaLegendEntry, AreaQuantity, DeviationRow } from "../series";

const hours = (magnitude: number) => `${magnitude.toFixed(1)}h`;

describe("a deviation row", () => {
  it("is refused an Area pigment by the typecheck", () => {
    const rendered = render(
      <DeviationBar
        caption="Scheduled against target"
        format={hours}
        rows={[
          {
            id: "career",
            label: "Career",
            actual: 27.3,
            target: 30,
            // @ts-expect-error a chart row is a chart context end to end: no Area ink, including the label cell
            pigment: "01",
          },
        ]}
      />,
    );

    expect(rendered.container.querySelector(".deviation__row")).not.toBeNull();
  });

  /* THE OTHER HALF OF "REJECTS OR IGNORES". A caller who assembles the row somewhere else hands in a wider object,
   * and a structural type accepts it: what must not happen is the pigment reaching an element. */
  it("ignores one that arrives through a variable the excess check does not see", () => {
    const fromElsewhere = {
      id: "career",
      label: "Career",
      actual: 27.3,
      target: 30,
      pigment: "01",
    };
    const rows: readonly DeviationRow[] = [fromElsewhere];
    const { container } = render(
      <DeviationBar caption="Scheduled against target" format={hours} rows={rows} />,
    );

    expect(container.innerHTML).not.toContain("chart-ink");
    expect(container.innerHTML).not.toContain("area-01");
  });
});

describe("a legend entry", () => {
  it("is refused without the Area's name", () => {
    // @ts-expect-error a chip on its own encodes a category in colour alone, which is never the only encoding
    const nameless: AreaLegendEntry = { id: "career", pigment: "01", figure: "14.2h" };
    const { container } = render(<AreaLegend label="Share" entries={[nameless]} />);

    expect(container.querySelectorAll(".legend__entry")).toHaveLength(1);
  });

  it("takes the vacancy, which is a category like any other here", () => {
    const vacancy: AreaLegendEntry = {
      id: "unallocated",
      label: "Unallocated",
      pigment: "unallocated",
      figure: "18.4h",
    };

    expect(vacancy.pigment).toBe("unallocated");
  });
});

describe("a category's pigment", () => {
  it("is a step of the sealed ramp or the vacancy, and nothing else", () => {
    // @ts-expect-error the ramp is sealed at twelve: a thirteenth step is a change to the design language
    const past: AreaQuantity = { id: "a", label: "A", pigment: "13", minutes: 60 };

    expect(past.minutes).toBe(60);
  });
});

describe("a meter", () => {
  it("is refused without the name of what it measures", () => {
    // @ts-expect-error a run of identical characters says nothing to a screen reader without a label
    const { container } = render(<MaturityMeter value={7} bound={14} />);

    expect(container.querySelector(".meter")).not.toBeNull();
  });
});

describe("a pie", () => {
  it("is refused without the caption that names it", () => {
    // @ts-expect-error the caption is the graphic's accessible name as well as its label
    const { container } = render(<PieChart slices={[]} />);

    expect(container.querySelector(".chart")).not.toBeNull();
  });
});
