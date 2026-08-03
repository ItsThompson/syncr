/* THE WIZARD'S ROWS, AND THE PROGRESS BAR THAT IS NOT THERE.
 *
 * Three claims: numbered rows with a caret on the current step, no bar of any kind, and a blocked step that a
 * reader can tell apart from one they simply have not started. The third is the one that matters most on first run,
 * because it is the dependency between the steps. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { WizardSteps, type WizardStep } from "../WizardSteps";

const STEPS: readonly WizardStep[] = [
  {
    id: "sources",
    label: "Connect a calendar to read anchors from",
    status: "done",
    note: "2 sources",
  },
  {
    id: "areas",
    label: "Declare your Areas and their budgets",
    status: "current",
    note: "required",
  },
  {
    id: "shape",
    label: "Build one day shape",
    status: "blocked",
    note: "blocked · needs your Areas",
  },
  {
    id: "bounds",
    label: "Set day bounds, sleep span and write target",
    status: "waiting",
    note: "optional",
  },
];

const stylesheet = () => kitStylesheet("wizard/wizard.css", domainDir);

const rows = () => screen.getAllByRole("listitem");

describe("the steps", () => {
  it("are an ordered list, which is what a wizard has instead of a bar", () => {
    render(<WizardSteps steps={STEPS} label="Setting up" />);

    expect(screen.getByRole("list", { name: "Setting up" })).toBeInTheDocument();
    expect(rows()).toHaveLength(4);
  });

  it("are numbered from their position, so two steps cannot both be 02", () => {
    render(<WizardSteps steps={STEPS} label="Setting up" />);

    expect(rows().map((row) => row.querySelector(".wizard__number")?.textContent)).toEqual([
      "01",
      "02",
      "03",
      "04",
    ]);
  });

  it("state each step's own note, which is where a blocker is said in words", () => {
    render(<WizardSteps steps={STEPS} label="Setting up" />);

    expect(screen.getByText("required")).toBeInTheDocument();
    expect(screen.getByText("blocked · needs your Areas")).toBeInTheDocument();
    expect(screen.getByText("optional")).toBeInTheDocument();
  });
});

describe("the current step", () => {
  it("carries the caret, and the caret lands on the row a screen reader is told about", () => {
    render(<WizardSteps steps={STEPS} label="Setting up" />);
    const current = rows().find((row) => row.getAttribute("aria-current") === "step");

    expect(current).toHaveTextContent("Declare your Areas");
    expect(current?.querySelector(".glyph--caret")).not.toBeNull();
  });

  it("takes the kit's row states rather than a fill of its own", () => {
    render(<WizardSteps steps={STEPS} label="Setting up" />);
    const current = rows()[1];

    expect(current).toHaveClass("state-row");
    expect(current).toHaveAttribute("data-current", "");
  });

  it("is the only row with a caret, so the position is unambiguous", () => {
    const { container } = render(<WizardSteps steps={STEPS} label="Setting up" />);

    expect(container.querySelectorAll(".glyph--caret")).toHaveLength(1);
  });
});

describe("a completed step", () => {
  it("takes the tick, which is the mark this kit already draws for a thing that is done", () => {
    const { container } = render(<WizardSteps steps={STEPS} label="Setting up" />);

    expect(rows()[0].querySelector(".glyph--check")).not.toBeNull();
    expect(container.querySelectorAll(".glyph--check")).toHaveLength(1);
  });
});

describe("a blocked step", () => {
  it("is visually distinct from a step not started", () => {
    render(<WizardSteps steps={STEPS} label="Setting up" />);

    expect(rows()[2]).toHaveClass("wizard__step--blocked");
    expect(rows()[3]).not.toHaveClass("wizard__step--blocked");
  });

  it("is distinguished by something that survives forced colors, not by colour alone", async () => {
    const css = await stylesheet();
    const blocked = /\.wizard__step--blocked\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";

    expect(blocked).toContain("border-left-style: dashed");
  });

  it("takes the oxide TEXT step for its note, because a note is words", async () => {
    const css = await stylesheet();

    expect(/\.wizard__step--blocked \.wizard__note\s*\{[^}]*--oxide-ink/.test(css)).toBe(true);
  });
});

describe("the wizard's stylesheet", () => {
  it("draws no bar, no fill that grows, and nothing that animates", async () => {
    const css = await stylesheet();

    for (const banned of ["animation", "transition", "keyframes", "width: calc(", "progress"]) {
      expect(css).not.toContain(banned);
    }
  });

  it("reserves the mark column, so becoming current changes a glyph rather than a width", async () => {
    const css = await stylesheet();

    expect(/\.wizard__mark\s*\{[^}]*width:\s*12px/.test(css)).toBe(true);
  });
});
