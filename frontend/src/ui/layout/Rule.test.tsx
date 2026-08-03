/* The hairline, the vertical form of it, and the rule that picks its ink by surface.
 *
 * The surface rule is the point: --rule measures 1.59:1 on paper and the same value on an ink header is
 * invisible, so the ink is chosen by the container the rule lands in rather than by a modifier a caller
 * remembers. That is the same shape as the focus ring, and for the same reason. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appliedDeclarations } from "../../testing/visualState";
import { kitStylesheet, layoutDir } from "../../testing/kitStylesheets";
import { Rule } from "./Rule";

const stylesheet = () => kitStylesheet("Rule.css", layoutDir);

describe("a rule", () => {
  it("is a separator a screen reader announces, rather than a styled div", () => {
    render(<Rule />);

    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("draws the hairline on paper", async () => {
    render(<Rule />);

    const declarations = appliedDeclarations({
      element: screen.getByRole("separator"),
      css: await stylesheet(),
    });
    expect(declarations).toContain("border-top: var(--hairline) solid var(--rule)");
  });

  it("says it is vertical, so its orientation is not read from its pixels", () => {
    render(<Rule orientation="vertical" />);

    expect(screen.getByRole("separator")).toHaveAttribute("aria-orientation", "vertical");
  });

  it("moves the hairline to the left edge when it is vertical", async () => {
    render(<Rule orientation="vertical" />);

    const declarations = appliedDeclarations({
      element: screen.getByRole("separator"),
      css: await stylesheet(),
    });
    expect(declarations).toContain("border-left: var(--hairline) solid var(--rule)");
    expect(declarations).toContain("border-top: 0");
  });

  it("steps to the on-ink ink inside an ink surface, in both orientations", async () => {
    const css = await stylesheet();
    const { container } = render(
      <div className="on-ink-surface">
        <Rule />
        <Rule orientation="vertical" />
      </div>,
    );
    const [horizontal, vertical] = [...container.querySelectorAll("hr")];

    expect(appliedDeclarations({ element: horizontal, css })).toContain(
      "border-top-color: var(--rule-on-ink)",
    );
    expect(appliedDeclarations({ element: vertical, css })).toContain(
      "border-left-color: var(--rule-on-ink)",
    );
  });
});
