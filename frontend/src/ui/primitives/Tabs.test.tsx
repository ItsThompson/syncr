/* Tabs: the kit's one disclosure surface.
 *
 * THE ACTIVE TAB TAKES THE --rule-emphasis BOTTOM RULE, in --ink-deep. The rule is reserved transparent at rest
 * so activating a tab changes a colour and not a width, which is the same discipline the current navigation row
 * is drawn with. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { Tabs } from "./Tabs";

const TABS = [
  { value: "days", label: "Day types", count: 4, content: <p>Four day types</p> },
  { value: "week", label: "Week pattern", count: 0, content: <p>The week pattern</p> },
  { value: "routines", label: "Routines", content: <p>Routines</p> },
];

function renderTabs(value = "days") {
  const onValueChange = vi.fn<(next: string) => void>();
  const result = render(
    <Tabs value={value} onValueChange={onValueChange} tabs={TABS} label="Templates sections" />,
  );
  return { onValueChange, ...result };
}

describe("Tabs", () => {
  it("names the strip, which is what a screen reader reads before the tabs", () => {
    renderTabs();

    expect(screen.getByRole("tablist", { name: "Templates sections" })).toBeInTheDocument();
  });

  it("renders one tab per entry", () => {
    renderTabs();

    expect(screen.getAllByRole("tab")).toHaveLength(TABS.length);
  });

  it("marks the active tab with Radix's own state, so nothing toggles a class", () => {
    renderTabs();
    const active = screen.getByRole("tab", { name: /Day types/ });

    expect(active).toHaveAttribute("data-state", "active");
    expect(active).toHaveAttribute("aria-selected", "true");
  });

  it("shows only the active panel", () => {
    renderTabs();

    expect(screen.getByText("Four day types")).toBeInTheDocument();
    expect(screen.queryByText("The week pattern")).toBeNull();
  });

  it("hands the caller the chosen tab", async () => {
    const { onValueChange } = renderTabs();

    await userEvent.click(screen.getByRole("tab", { name: /Week pattern/ }));

    expect(onValueChange).toHaveBeenCalledWith("week");
  });

  /* A tab that vanishes when its list empties makes a reader wonder whether the feature exists. */
  it("shows a count of zero rather than hiding it", () => {
    renderTabs();

    expect(screen.getByRole("tab", { name: /Week pattern/ })).toHaveTextContent("0");
  });

  it("shows no count at all for a tab that counts nothing", () => {
    renderTabs();

    expect(screen.getByRole("tab", { name: "Routines" })).toHaveTextContent(/^Routines$/);
  });
});

describe("the tabs stylesheet", () => {
  it("gives the active tab the emphasised bottom rule in ink", async () => {
    const css = await kitStylesheet("Tabs.css");
    const active = /\.tabs__trigger\[data-state="active"\]\s*\{([^}]*)\}/.exec(css);

    expect(active?.[1]).toContain("border-bottom-color: var(--ink-deep)");
  });

  it("reserves the rule's width at rest, so activating changes a colour and not a height", async () => {
    const css = await kitStylesheet("Tabs.css");
    const atRest = /\.tabs__trigger\s*\{([^}]*)\}/.exec(css);

    expect(atRest?.[1]).toContain("border-bottom: var(--rule-emphasis) solid transparent");
  });

  it("reads the emphasised weight from its token rather than restating 2px", async () => {
    const declarations = (await kitStylesheet("Tabs.css")).replace(/\/\*[\s\S]*?\*\//g, "");

    expect(declarations).not.toMatch(/border-bottom:\s*2px/);
  });
});
