/* The icon, and the one rule that matters about it: the values come from tokens.
 *
 * Hard-coding `strokeLinecap="round"` is a review failure even though it produces the same output today,
 * because the inherited language's two reference sheets diverged once when its tokens were silent on caps. So
 * the assertions are about the chain: the component carries the class, the class declares the three
 * properties, and each declaration reads the token rather than a literal. */

import { Inbox } from "lucide-react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { Icon } from "./Icon";

function renderedIcon(container: HTMLElement): SVGSVGElement {
  const svg = container.querySelector("svg");
  if (svg === null) throw new Error("no icon rendered");
  return svg;
}

describe("Icon", () => {
  it("renders the lucide mark it was given", () => {
    const { container } = render(<Icon mark={Inbox} />);

    expect(renderedIcon(container)).toBeInTheDocument();
  });

  it("is decorative by default, because it sits beside the label it illustrates", () => {
    const { container } = render(<Icon mark={Inbox} />);

    expect(renderedIcon(container)).toHaveAttribute("aria-hidden", "true");
  });

  it("takes an accessible name where it is the only name a control has", () => {
    render(<Icon mark={Inbox} label="Backlog" />);

    expect(screen.getByRole("img", { name: "Backlog" })).toBeInTheDocument();
  });

  it.each([
    ["sm", "icon--sm"],
    ["lg", "icon--lg"],
  ] as const)("draws the %s size through a variant class", (size, expected) => {
    const { container } = render(<Icon mark={Inbox} size={size} />);

    expect([...renderedIcon(container).classList]).toContain(expected);
  });

  it("draws the base size with the class alone, so the token is the default", () => {
    const { container } = render(<Icon mark={Inbox} />);
    const classes = [...renderedIcon(container).classList];

    expect(classes).toContain("icon");
    expect(classes).not.toContain("icon--sm");
    expect(classes).not.toContain("icon--lg");
  });
});

describe("the icon stylesheet", () => {
  it("reads the stroke, the caps and the joins from tokens rather than restating them", async () => {
    const css = await kitStylesheet("Icon.css");

    expect(css).toContain("stroke-width: var(--icon-stroke)");
    expect(css).toContain("stroke-linecap: var(--icon-cap)");
    expect(css).toContain("stroke-linejoin: var(--icon-join)");
  });

  it("reads all three sizes from tokens, and offers no fourth", async () => {
    const css = (await kitStylesheet("Icon.css")).replace(/\/\*[\s\S]*?\*\//g, "");

    expect(css).toContain("width: var(--icon-sm)");
    expect(css).toContain("width: var(--icon)");
    expect(css).toContain("width: var(--icon-lg)");
    expect([...css.matchAll(/\.icon(--[a-z]+)?\s*\{/g)]).toHaveLength(3);
  });

  it("states no literal length or weight of its own", async () => {
    const declarations = (await kitStylesheet("Icon.css")).replace(/\/\*[\s\S]*?\*\//g, "");

    expect(declarations).not.toMatch(/:\s*\d+(px)?;/);
    expect(declarations).not.toContain("round");
  });
});
