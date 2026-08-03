/* The button's four ranks, and the two claims the ticket makes about them.
 *
 * NO RANK CARRIES A SHADOW: the one hard offset lifts an overlay off the page, and a button is in the flow.
 * A PRIMARY BUTTON KEEPS THE STANDARD RING: its fill is ink but its parent is paper, and the ring is chosen by
 * the surface it lands on. Both are asserted against the stylesheet, because jsdom applies none. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { appliedDeclarations } from "../../testing/visualState";
import { Button } from "./Button";

const RANKS = ["primary", "secondary", "tertiary", "quiet"] as const;

describe("Button", () => {
  it("renders a real button that submits nothing by default", () => {
    render(<Button onClick={() => {}}>Approve week</Button>);

    expect(screen.getByRole("button", { name: "Approve week" })).toHaveAttribute("type", "button");
  });

  it("calls back on a click", async () => {
    const onClick = vi.fn<() => void>();
    render(<Button onClick={onClick}>Approve week</Button>);

    await userEvent.click(screen.getByRole("button"));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it.each(RANKS)("draws the %s rank from a variant rather than from a caller's classes", (rank) => {
    render(<Button rank={rank}>Propose</Button>);
    const classes = [...screen.getByRole("button").classList];

    expect(classes).toContain("button");
    // The primary rank is the base class, so it has no modifier of its own to find.
    expect(classes.includes(`button--${rank}`)).toBe(rank !== "primary");
  });

  it("submits only where a form means it to", () => {
    render(<Button type="submit">Save</Button>);

    expect(screen.getByRole("button")).toHaveAttribute("type", "submit");
  });

  it("is disabled in both forms, so a focusable disabled control reads the same", () => {
    render(<Button isDisabled>Approve all</Button>);
    const button = screen.getByRole("button");

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
  });

  it("takes its accessible name from the label where the child is a glyph", () => {
    render(
      <Button label="Close">
        <span className="glyph glyph--cross" aria-hidden="true" />
      </Button>,
    );

    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  /* A button that NAVIGATES renders a real link. `asChild` is the mechanism: an anchor with an href keeps
   * middle-click, cmd-click and the browser's own affordances, and `window.location` keeps none of them. */
  it("renders the caller's own element with asChild, so navigation is a real link", () => {
    render(
      <MemoryRouter>
        <Button asChild>
          <Link to="/week">Open the week</Link>
        </Button>
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Open the week" });

    expect(link).toHaveAttribute("href", "/week");
    expect(link.classList).toContain("button");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("forwards a ref to the element the caller will focus", () => {
    let node: HTMLButtonElement | null = null;
    render(
      <Button
        ref={(element) => {
          node = element;
        }}
      >
        Approve
      </Button>,
    );

    expect(node).toBeInstanceOf(HTMLButtonElement);
  });
});

describe("the button's stylesheet", () => {
  it("carries no shadow at any rank, because the hard offset belongs to overlays", async () => {
    expect(await kitStylesheet("Button.css")).not.toMatch(/^\s*box-shadow:/m);
  });

  it("declares no focus ring, so the primary rank keeps the standard one from the surface", async () => {
    const declarations = (await kitStylesheet("Button.css")).replace(/\/\*[\s\S]*?\*\//g, "");

    expect(declarations).not.toContain("outline");
  });

  it("reads its heights from the control tokens rather than restating them", async () => {
    const css = await kitStylesheet("Button.css");

    expect(css).toContain("height: var(--h-control)");
    expect(css).toContain("height: var(--h-control-sm)");
    expect(css).toContain("height: var(--h-control-lg)");
  });

  it("gives a disabled button the dashed border that means disabled in this system", async () => {
    const { container } = render(<Button isDisabled>Approve all</Button>);
    const button = container.querySelector("button");
    if (button === null) throw new Error("no button rendered");

    const applied = appliedDeclarations({
      element: button,
      css: await kitStylesheet("Button.css"),
    });

    expect(applied).toContain("border-style: dashed");
    expect(applied).toContain("color: var(--text-muted)");
  });
});
