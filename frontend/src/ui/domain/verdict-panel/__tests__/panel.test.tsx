/* THE VERDICT PANEL'S TWO RULES, AND THE ONE THING IT MUST NEVER DO.
 *
 * The two rules are section 09's: the height is FIXED with the rows scrolling inside it, and the panel shares that
 * height with the strip's verdict cell. Both are declarations, so both are read out of the stylesheet -- jsdom
 * applies none, and a rendered element says nothing about what a rule declares.
 *
 * The thing it must never do is CHOOSE. syncr enumerates and stops, so no row is selected, recommended, defaulted or
 * pressed, and asking for one sends nothing until the reader asks. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { parse } from "postcss";

import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { VerdictPanel } from "../VerdictPanel";
import { formatMinutes, verdictDetail, verdictHeadline } from "../verdict";
import type {
  PanelVerdict,
  VerdictConcession,
  VerdictShortfall,
  VerdictTradeoff,
} from "../verdict";

function shortfall(overrides: Partial<VerdictShortfall> = {}): VerdictShortfall {
  return {
    id: "deadline_capacity:career",
    kind: "deadline_capacity",
    shortfall: "1h20m",
    against: ["F&F Past Papers"],
    honoring: ["Fitness floor 5h"],
    deadline: "Fri 09:00",
    ...overrides,
  };
}

function tradeoff(overrides: Partial<VerdictTradeoff> = {}): VerdictTradeoff {
  return {
    kind: "accept_partial",
    label: "Accept partial delivery on F&F Past Papers",
    targetId: "5c9e0d4f-6a12-4f3a-8b21-7d2b1a904c6e",
    recovers: "1h20m",
    ...overrides,
  };
}

function verdict(overrides: Partial<PanelVerdict> = {}): PanelVerdict {
  return {
    provenance: "probe",
    isFeasible: false,
    capacityIsSufficient: false,
    shortfalls: [shortfall()],
    tradeoffs: [tradeoff()],
    ...overrides,
  };
}

const CONCESSIONS: VerdictConcession[] = [
  { id: "a1", label: "Sleep reduced by 1h across three nights", approvedOn: "Sun 09 Feb" },
  { id: "a2", label: "Fitness floor breached by 1h20m", approvedOn: "Sun 09 Feb" },
];

/** The declarations one selector makes, exactly as written. */
async function rule(selector: string): Promise<[string, string][]> {
  const found: [string, string][] = [];
  parse(await kitStylesheet("verdict-panel/verdict.css", domainDir)).walkRules((each) => {
    if (each.selector !== selector) return;
    each.walkDecls((declaration) => {
      found.push([declaration.prop, declaration.value]);
    });
  });
  return found;
}

describe("the height is fixed and the rows scroll inside it", () => {
  it("spends the token the strip's verdict cell shares, so the two cannot drift", async () => {
    expect(await rule(".verdict-panel")).toContainEqual(["height", "var(--verdict-h)"]);
  });

  it("scrolls the rows, with no scrollbar affordance to change their width", async () => {
    const rows = await rule(".verdict-panel__rows");

    expect(rows).toContainEqual(["overflow-y", "auto"]);
    /* The clipped edge of the fourth row IS the affordance. A scrollbar would also narrow the rows as they grow,
     * which is motion by another name. */
    expect(rows).toContainEqual(["scrollbar-width", "none"]);
    expect(rows).toContainEqual(["min-height", "0"]);
  });

  it("adds rows and never height when pins accumulate", () => {
    const one = render(<VerdictPanel verdict={verdict()} />);
    const oneRows = one.container.querySelectorAll(".verdict-panel__row").length;
    const oneClass = one.container.querySelector(".verdict-panel")?.className;

    const many = render(
      <VerdictPanel
        concessions={CONCESSIONS}
        verdict={verdict({
          shortfalls: [
            shortfall(),
            shortfall({ id: "s2", against: ["Career"] }),
            shortfall({ id: "s3", against: ["Fitness"] }),
          ],
          tradeoffs: [
            tradeoff(),
            tradeoff({ kind: "drop_item", targetId: "t2", label: "Drop Read for this week" }),
            tradeoff({ kind: "breach_floor", targetId: "t3", label: "Breach the Fitness floor" }),
          ],
        })}
      />,
    );

    expect(many.container.querySelectorAll(".verdict-panel__row").length).toBeGreaterThan(oneRows);
    /* The element carries no height of its own and no variant that could: one class list for both. */
    expect(many.container.querySelector(".verdict-panel")?.className).toBe(oneClass);
    expect(many.container.querySelector(".verdict-panel")?.getAttribute("style")).toBeNull();
  });

  /* A FOURTH ROW IS IN THE DOM RATHER THAN PAGINATED AWAY, which is the half of "partially visible" a jsdom
   * rendering can answer: the row exists and the container clips it. Whether its clipped edge is visible at 226px
   * is a rendered-pixel claim, and `scripts/check-render` is where a pixel claim belongs. */
  it("keeps every row in the document, so the fourth is clipped rather than dropped", () => {
    const { container } = render(
      <VerdictPanel
        verdict={verdict({
          shortfalls: [],
          tradeoffs: [
            tradeoff({ targetId: "t1" }),
            tradeoff({ targetId: "t2" }),
            tradeoff({ targetId: "t3" }),
            tradeoff({ targetId: "t4" }),
          ],
        })}
      />,
    );

    expect(container.querySelectorAll(".verdict-panel__row")).toHaveLength(4);
  });
});

describe("what the panel states", () => {
  it("names the provenance, so the product never asserts what it did not compute", () => {
    render(<VerdictPanel verdict={verdict({ provenance: "probe" })} />);

    expect(screen.getByText("capacity check")).toBeInTheDocument();
  });

  it("calls a solver verdict authoritative", () => {
    render(<VerdictPanel verdict={verdict({ provenance: "solver", shortfalls: [] })} />);

    expect(screen.getByText("authoritative")).toBeInTheDocument();
  });

  it("states the shortfall, the named commitment, the deadline and the constraint honored", () => {
    render(<VerdictPanel verdict={verdict()} />);

    expect(screen.getByText("1h20m short")).toBeInTheDocument();
    expect(screen.getByText("F&F Past Papers")).toBeInTheDocument();
    expect(screen.getByText("Fri 09:00")).toBeInTheDocument();
    expect(screen.getByText("Fitness floor 5h")).toBeInTheDocument();
  });

  it("lists applied concessions ABOVE the shortfalls", () => {
    const { container } = render(<VerdictPanel concessions={CONCESSIONS} verdict={verdict()} />);
    const text = [...container.querySelectorAll(".verdict-panel__row")].map(
      (row) => row.textContent ?? "",
    );

    expect(text[0]).toContain("Sleep reduced by 1h across three nights");
    expect(text[1]).toContain("Fitness floor breached by 1h20m");
    expect(text[2]).toContain("F&F Past Papers");
  });

  it("says so when a reading names no concession for a gap it reports", () => {
    render(<VerdictPanel verdict={verdict({ tradeoffs: [] })} />);

    expect(screen.getByText(/names no concession/)).toBeInTheDocument();
  });

  it("says nothing of the kind when every gap has an offer", () => {
    render(<VerdictPanel verdict={verdict()} />);

    expect(screen.queryByText(/names no concession/)).not.toBeInTheDocument();
  });
});

describe("a tradeoff is offered and never chosen", () => {
  it("is a statement plus a Propose button", () => {
    render(
      <VerdictPanel onPropose={vi.fn<(one: VerdictTradeoff) => void>()} verdict={verdict()} />,
    );

    expect(screen.getByText("Accept partial delivery on F&F Past Papers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Propose" })).toBeInTheDocument();
  });

  it("selects none of them: no row is pressed, checked, selected or current", () => {
    const { container } = render(
      <VerdictPanel
        onPropose={vi.fn<(one: VerdictTradeoff) => void>()}
        verdict={verdict({
          tradeoffs: [tradeoff({ targetId: "t1" }), tradeoff({ targetId: "t2" })],
        })}
      />,
    );

    for (const attribute of [
      "aria-pressed",
      "aria-selected",
      "aria-checked",
      "aria-current",
      "data-selected",
      "checked",
    ]) {
      expect(container.querySelectorAll(`[${attribute}]`)).toHaveLength(0);
    }
  });

  it("sends nothing until the reader asks, and then sends the tradeoff asked for", async () => {
    const onPropose = vi.fn<(one: VerdictTradeoff) => void>();
    const asked = tradeoff({ kind: "drop_item", targetId: "t2", label: "Drop Read for this week" });
    render(
      <VerdictPanel onPropose={onPropose} verdict={verdict({ tradeoffs: [tradeoff(), asked] })} />,
    );

    expect(onPropose).not.toHaveBeenCalled();

    await userEvent.click(screen.getAllByRole("button", { name: "Propose" })[1]);

    expect(onPropose).toHaveBeenCalledExactlyOnceWith(asked);
  });

  it("renders the offers with no control at all when nothing can be dispatched", () => {
    render(<VerdictPanel verdict={verdict()} />);

    expect(screen.getByText("Accept partial delivery on F&F Past Papers")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("infeasibility is a notice, not a failure", () => {
  it("is drawn in amber at panel volume", async () => {
    const panel = await rule(".verdict-panel");

    expect(panel).toContainEqual(["border-left", "var(--rule-emphasis) solid var(--signal-amber)"]);
    expect(panel).toContainEqual(["background-color", "var(--amber-wash)"]);
  });

  it("raises no alert, because nothing is broken", () => {
    render(<VerdictPanel verdict={verdict()} />);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("the wording", () => {
  it.each([
    [80, "1h20m"],
    [45, "45m"],
    [120, "2h"],
    [0, "0m"],
  ])("reads %i minutes as %s", (minutes, expected) => {
    expect(formatMinutes(minutes)).toBe(expected);
  });

  it("never claims a week is feasible on probe evidence alone", () => {
    const clean = verdict({ provenance: "probe", shortfalls: [], tradeoffs: [] });

    expect(verdictHeadline(clean, 0)).toBe("No shortfall found in this week's capacity");
  });

  it("says a week holds only from an attempted placement", () => {
    const solved = verdict({
      provenance: "solver",
      shortfalls: [],
      tradeoffs: [],
      isFeasible: true,
    });

    expect(verdictHeadline(solved, 0)).toBe("This week holds its commitments");
    expect(verdictHeadline(solved, 2)).toBe("This week holds, with 2 concessions");
    expect(verdictHeadline(solved, 1)).toBe("This week holds, with one concession");
  });

  it("gives the strip the first gap in the verdict's own words", () => {
    expect(verdictDetail(verdict())).toBe("1h20m short on F&F Past Papers before Fri 09:00");
  });

  it("gives the strip the provenance when there is no gap", () => {
    expect(verdictDetail(verdict({ shortfalls: [] }))).toBe("capacity check · no gap");
  });
});
