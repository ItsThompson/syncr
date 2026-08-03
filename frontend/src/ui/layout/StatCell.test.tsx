/* The figure cells, and the one rule they exist to hold: a headline number is mono, never serif.
 *
 * The assertion is over the stylesheet rather than over a rendered element, because jsdom applies no
 * stylesheet and `getComputedStyle` on the rendered figure would report nothing whether the rule exists or
 * not. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { kitStylesheet, layoutDir } from "../../testing/kitStylesheets";
import { Card } from "./Card";
import { StatCell } from "./StatCell";

describe("a stat cell", () => {
  it("renders the label, the figure and the sub-line", () => {
    render(<StatCell label="Scheduled" figure="91" sub="solving" />);

    expect(screen.getByText("Scheduled")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getByText("solving")).toBeInTheDocument();
  });

  it("omits the sub-line when there is no qualifier, so the cell does not reserve a blank one", () => {
    const { container } = render(<StatCell label="Scheduled" figure="91" />);

    expect(container.querySelector(".stat-cell__sub")).toBeNull();
  });

  it("sets its figure in mono with tabular digits", async () => {
    const css = await kitStylesheet("StatCell.css", layoutDir);
    const figure = /\.stat-cell__figure\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";

    expect(figure).toContain("font-family: var(--font-mono)");
    expect(figure).toContain("font-variant-numeric: tabular-nums");
  });

  it("names the serif nowhere in the layer, which is what the two-place rule means", async () => {
    const css = await kitStylesheet("StatCell.css", layoutDir);

    expect(css).not.toContain("--font-serif");
  });
});

describe("a card", () => {
  it("is one figure inside the block every other surface uses", () => {
    const { container } = render(<Card label="Deviation" figure="+4%" footer="against target" />);

    expect(container.querySelector(".panel")).not.toBeNull();
    expect(container.querySelectorAll(".stat-cell")).toHaveLength(1);
    expect(container.querySelector(".panel__footer")).toHaveTextContent("against target");
  });

  it("draws no header, because a card announces its figure through the cell's own label", () => {
    const { container } = render(<Card label="Deviation" figure="+4%" />);

    expect(container.querySelector(".panel__header")).toBeNull();
    expect(screen.getByText("Deviation")).toBeInTheDocument();
  });
});
