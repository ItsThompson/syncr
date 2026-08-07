/* ROWS, NEVER A PARAGRAPH, AND ONE LABEL COLUMN FOR BOTH SURFACES THAT DRAW THEM.
 *
 * The rendering answers the first: a definition list is a term and a description, which is what a clause is. The
 * width is a declaration, so it is read out of the stylesheet, and the token is asserted to be the shared one rather
 * than a length this sheet chose: three sheets had independently chosen 60px, 64px and 76px before it was a token. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { ReasonRows } from "../ReasonRows";

const PINNED_BLOCK = [
  { label: "pinned", value: "Tue 05:30 \u00b7 you moved it here on Sun 09 Feb" },
  { label: "instead of", value: "13:15 \u00b7 what the solver proposed" },
  { label: "cost", value: "timeOfDayMisfit \u00b7 +0.18 against the proposal" },
  { label: "floor", value: "Fitness 5h \u00b7 3 of 4 occurrences placed" },
];

async function declarations(selector: string): Promise<[string, string][]> {
  const found: [string, string][] = [];
  parse(await kitStylesheet("reason-rows/rows.css", domainDir)).walkRules((each) => {
    if (each.selector !== selector) return;
    each.walkDecls((declaration) => {
      found.push([declaration.prop, declaration.value]);
    });
  });
  return found;
}

describe("the rendering", () => {
  it("is a definition list: a term and a description per row", () => {
    const { container } = render(<ReasonRows rows={PINNED_BLOCK} />);

    expect(container.querySelectorAll("dt")).toHaveLength(4);
    expect(container.querySelectorAll("dd")).toHaveLength(4);
    expect(container.querySelectorAll("p")).toHaveLength(0);
  });

  it("renders each label beside its own value", () => {
    render(<ReasonRows rows={PINNED_BLOCK} />);

    expect(screen.getByText("instead of")).toBeInTheDocument();
    expect(screen.getByText("13:15 \u00b7 what the solver proposed")).toBeInTheDocument();
  });

  it("draws nothing for an empty set, so the caller says what an absence means", () => {
    const { container } = render(<ReasonRows rows={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names the list where a caller gives it a name", () => {
    render(<ReasonRows label="Reason" rows={PINNED_BLOCK} />);

    expect(screen.getByLabelText("Reason")).toBeInTheDocument();
  });
});

describe("the label column", () => {
  it("reads the shared token rather than a length this sheet chose", async () => {
    expect(await declarations(".reason-rows")).toContainEqual([
      "grid-template-columns",
      "var(--clause-label-w) minmax(0, 1fr)",
    ]);
  });

  it("wraps a long value rather than truncating it, because the tail is what distinguishes one", async () => {
    const value = await declarations(".reason-rows__value");

    expect(value).toContainEqual(["overflow-wrap", "break-word"]);
    expect(value.map(([property]) => property)).not.toContain("text-overflow");
    expect(value.map(([property]) => property)).not.toContain("white-space");
  });
});
