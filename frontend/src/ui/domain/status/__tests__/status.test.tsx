/* THE THREE SURFACES WITH NOTHING TO SHOW, AND THE THING NONE OF THEM DOES.
 *
 * The claim worth a test is the absence: no spinner, no skeleton, no shimmer, and nothing that could become one.
 * It is asserted twice over, in the rendering and in the stylesheet, because "static" is a property of what ships
 * rather than of what a component meant. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "../../../primitives";
import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { EmptyState } from "../EmptyState";
import { ErrorState } from "../ErrorState";
import { PendingState } from "../PendingState";

const stylesheet = () => kitStylesheet("status/status.css", domainDir);

describe("an empty state", () => {
  it("says what is not here and what to do about it", () => {
    render(
      <EmptyState
        title="This week is beyond your 14-day planning horizon."
        detail="A week past the horizon has no plan by design, because a read never triggers work."
        action={<Button rank="secondary">Solve this week now</Button>}
      />,
    );

    expect(screen.getByText(/beyond your 14-day planning horizon/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve this week now" })).toBeInTheDocument();
  });

  it("takes the caller's plate, which is one of the five surfaces illustration is allowed on", () => {
    const { container } = render(
      <EmptyState
        title="Nothing captured yet"
        detail="Press n."
        plate={<img alt="" src="p.png" />}
      />,
    );

    expect(container.querySelector("img")).toBeInTheDocument();
  });

  it("is announced as neither a status nor an alert, because it IS the screen's content", () => {
    render(<EmptyState title="Nothing captured yet" detail="Press n." />);

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("a pending state", () => {
  it("names what is being waited for, which is what it has instead of a spinner", () => {
    render(<PendingState title="Solving this week" detail="The plan on screen is the last one." />);

    expect(screen.getByRole("status")).toHaveTextContent("Solving this week");
  });

  it("offers no action, because waiting is not a state a reader repairs", () => {
    render(<PendingState title="Solving this week" detail="The plan on screen is the last one." />);

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("an error state", () => {
  it("interrupts, which is the one surface in this family that does", () => {
    render(<ErrorState title="The week could not be read" detail="Your plan is unchanged." />);

    expect(screen.getByRole("alert")).toHaveTextContent("The week could not be read");
  });

  it("marks itself with the cross rather than with colour alone", () => {
    const { container } = render(
      <ErrorState title="The week could not be read" detail="Your plan is unchanged." />,
    );

    expect(container.querySelector(".status__mark")).toHaveClass("glyph--cross");
  });

  it("takes the oxide TEXT step for its title, because a title is words", async () => {
    const css = await stylesheet();

    expect(css).toContain("var(--oxide-ink)");
    expect(/\.status--error \.status__title\s*\{[^}]*--oxide-ink/.test(css)).toBe(true);
  });

  it("takes the marker step for its mark, where 3:1 is the bar", async () => {
    const css = await stylesheet();

    expect(/\.status--error \.status__mark\s*\{[^}]*--signal-oxide/.test(css)).toBe(true);
  });
});

describe("none of the three", () => {
  it("spins, animates, shimmers or transitions, in any spelling", async () => {
    const css = await stylesheet();

    for (const banned of ["animation", "transition", "transform", "@keyframes", "will-change"]) {
      expect(css).not.toContain(banned);
    }
  });

  it("draws a spinner-shaped thing either: no radius, no border cut from a circle", async () => {
    const css = await stylesheet();

    expect(css).not.toContain("border-radius");
  });
});
