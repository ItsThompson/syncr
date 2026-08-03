/* The bordered block and its ink header.
 *
 * The header's `on-ink-surface` class is the assertion that matters. It is not decoration: `base.css` gives
 * every focusable descendant of that class the INVERSE focus ring, because --ink-bright on --ink-deep measures
 * 1.61:1 and vanishes, so a control a later ticket puts in this header depends on the class being there. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "../primitives";
import { Panel } from "./Panel";

describe("a titled panel", () => {
  it("names its region with the title, so a reader can jump to it", () => {
    render(<Panel title="Verdict">infeasible by 45 minutes</Panel>);

    expect(screen.getByRole("region", { name: "Verdict" })).toBeInTheDocument();
  });

  it("says the title once, as a heading the region is labelled by", () => {
    render(<Panel title="Verdict">infeasible by 45 minutes</Panel>);

    expect(screen.getAllByText("Verdict")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Verdict" })).toBeInTheDocument();
  });

  it("wraps the header in on-ink-surface, which is where the inverse ring comes from", () => {
    render(<Panel title="Verdict">rows</Panel>);

    const header = screen.getByRole("heading", { name: "Verdict" }).parentElement;
    expect(header).toHaveClass("on-ink-surface");
  });

  it("puts a header control inside that surface, so it inherits the ring", () => {
    render(
      <Panel title="Verdict" headerEnd={<Button rank="quiet">Re-solve</Button>}>
        rows
      </Panel>,
    );

    expect(
      screen.getByRole("button", { name: "Re-solve" }).closest(".on-ink-surface"),
    ).not.toBeNull();
  });

  it("is the only element in the tree carrying the ink surface", () => {
    const { container } = render(<Panel title="Verdict">rows</Panel>);

    expect(container.querySelectorAll(".on-ink-surface")).toHaveLength(1);
  });
});

describe("an untitled panel", () => {
  it("draws no header at all, because the ink fill is what a title earns", () => {
    const { container } = render(<Panel>a figure</Panel>);

    expect(container.querySelector(".panel__header")).toBeNull();
    expect(container.querySelector(".on-ink-surface")).toBeNull();
  });

  it("is a plain section rather than an unnamed region", () => {
    render(<Panel>a figure</Panel>);

    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.getByText("a figure")).toBeInTheDocument();
  });
});

describe("the footer", () => {
  it("is rendered under the body when there is one", () => {
    const { container } = render(<Panel footer="37 rows">body</Panel>);

    expect(container.querySelector(".panel__footer")).toHaveTextContent("37 rows");
  });

  it("is absent otherwise, so a panel with nothing to footnote has no hairline", () => {
    const { container } = render(<Panel>body</Panel>);

    expect(container.querySelector(".panel__footer")).toBeNull();
  });
});
