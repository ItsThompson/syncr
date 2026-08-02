/* The command list, and the rule section 14 states twice: `data-highlighted` maps to focus and NOTHING else.
 *
 * The cursor and the current row are two states. The cursor is where the keyboard is; the current row is the one
 * the palette was opened from. Giving the cursor the hover wash as well would make a hovered row and the cursor
 * row indistinguishable, which is the collision the closed vocabulary exists to prevent.
 *
 * Focus stays in the query field throughout: the rows are options and the field points at one with
 * `aria-activedescendant`, so a reader can keep typing while the cursor moves. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { appliedDeclarations } from "../../testing/visualState";
import { Command } from "./Command";

const ACTIONS = [
  { id: "approve", label: "Approve week", group: "Plan", hint: "shift a" },
  { id: "capture", label: "Capture a task", group: "Plan", hint: "n" },
  { id: "week", label: "Go to Week", group: "Navigate", isCurrent: true },
  { id: "today", label: "Go to Today", group: "Navigate" },
];

function renderCommand(props: Partial<Parameters<typeof Command>[0]> = {}) {
  const onSelect = vi.fn<(id: string) => void>();
  const result = render(
    <Command
      actions={ACTIONS}
      onSelect={onSelect}
      label="Command palette"
      placeholder="Type a command"
      emptyLabel="No command matches"
      {...props}
    />,
  );
  return { onSelect, ...result };
}

describe("Command", () => {
  it("is a combobox naming itself, with a listbox it controls", () => {
    renderCommand();
    const field = screen.getByRole("combobox", { name: "Command palette" });

    /* The ids are scoped rather than fixed, so two palettes cannot both answer to `command-list`. What
     * matters is that the field points at the list that is actually there. */
    expect(field.getAttribute("aria-controls")).toBe(screen.getByRole("listbox").id);
    expect(screen.getByRole("listbox").id).not.toBe("");
  });

  it("points at the cursor's row by the row's own id, not by the caller's action id", () => {
    renderCommand();
    const field = screen.getByRole("combobox");
    const cursor = screen.getByRole("option", { name: /Approve week/ });

    expect(field.getAttribute("aria-activedescendant")).toBe(cursor.id);
    expect(cursor.id).toMatch(/approve$/);
  });

  it("lists every action, under the group it belongs to", () => {
    renderCommand();

    expect(screen.getAllByRole("option")).toHaveLength(ACTIONS.length);
    expect(screen.getByRole("group", { name: "Plan" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Navigate" })).toBeInTheDocument();
  });

  it("filters on what a reader types, case-insensitively", async () => {
    renderCommand();

    await userEvent.type(screen.getByRole("combobox"), "week");

    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.getByRole("option", { name: /Approve week/ })).toBeInTheDocument();
  });

  it("says so when nothing matches, rather than showing an empty box", async () => {
    renderCommand();

    await userEvent.type(screen.getByRole("combobox"), "zzz");

    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByText("No command matches")).toBeInTheDocument();
  });

  it("starts with the cursor on the first row", () => {
    renderCommand();

    expect(screen.getByRole("combobox").getAttribute("aria-activedescendant")).toBe(
      screen.getByRole("option", { name: /Approve week/ }).id,
    );
  });

  it("moves the cursor with the arrow keys and keeps focus in the field", async () => {
    renderCommand();
    const field = screen.getByRole("combobox");

    field.focus();
    await userEvent.keyboard("{ArrowDown}");

    expect(field.getAttribute("aria-activedescendant")).toBe(
      screen.getByRole("option", { name: /Capture a task/ }).id,
    );
    expect(field).toHaveFocus();
  });

  it("wraps at the end of the list rather than stopping", async () => {
    renderCommand();
    const field = screen.getByRole("combobox");

    field.focus();
    await userEvent.keyboard("{ArrowUp}");

    expect(field.getAttribute("aria-activedescendant")).toBe(
      screen.getByRole("option", { name: /Go to Today/ }).id,
    );
  });

  it("selects the cursor's row on Enter", async () => {
    const { onSelect } = renderCommand();

    screen.getByRole("combobox").focus();
    await userEvent.keyboard("{ArrowDown}{Enter}");

    expect(onSelect).toHaveBeenCalledWith("capture");
  });

  it("selects a row on a click", async () => {
    const { onSelect } = renderCommand();

    await userEvent.click(screen.getByRole("option", { name: /Go to Today/ }));

    expect(onSelect).toHaveBeenCalledWith("today");
  });

  /* THE CURSOR IS DERIVED, NOT STORED. A stored index goes stale the moment the query narrows the list under it,
   * and the usual repair is an effect that resets it after the render that was already wrong. */
  it("keeps the cursor on a row that survives the filter", async () => {
    renderCommand();
    const field = screen.getByRole("combobox");

    field.focus();
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.type(field, "capture");

    expect(field.getAttribute("aria-activedescendant")).toBe(
      screen.getByRole("option", { name: /Capture a task/ }).id,
    );
  });

  it("falls back to the first result when the cursor's row is filtered out", async () => {
    renderCommand();
    const field = screen.getByRole("combobox");

    field.focus();
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.type(field, "go to");

    expect(field.getAttribute("aria-activedescendant")).toBe(
      screen.getByRole("option", { name: /Go to Week/ }).id,
    );
  });
});

describe("the cursor and the current row", () => {
  it("marks the cursor with data-highlighted and the palette's own row with data-current", () => {
    renderCommand();

    expect(screen.getByRole("option", { name: /Approve week/ })).toHaveAttribute(
      "data-highlighted",
      "",
    );
    expect(screen.getByRole("option", { name: /Go to Week/ })).toHaveAttribute("data-current", "");
  });

  it("marks exactly one row as the cursor", () => {
    const { container } = renderCommand();

    expect(container.querySelectorAll("[data-highlighted]")).toHaveLength(1);
  });

  it("gives the cursor the ring and nothing else, so a hovered row stays distinguishable", async () => {
    renderCommand();
    const cursor = screen.getByRole("option", { name: /Approve week/ });
    const applied = appliedDeclarations({
      element: cursor,
      css: await kitStylesheet("states.css"),
    });

    expect(applied.some((declaration) => declaration.startsWith("outline:"))).toBe(true);
    expect(applied.some((declaration) => declaration.startsWith("background"))).toBe(false);
  });

  it("gives the current row the fill and the left rule, which is any current row's channel", async () => {
    renderCommand();
    const current = screen.getByRole("option", { name: /Go to Week/ });
    const applied = appliedDeclarations({
      element: current,
      css: await kitStylesheet("states.css"),
    });

    expect(applied).toContain("background-color: var(--state-hover)");
    expect(applied).toContain("border-left-color: var(--state-selected-color)");
  });

  it("draws the cursor's ring at a negative offset, because rows pitch at the row height", async () => {
    const css = await kitStylesheet("states.css");
    const highlighted = /\.state-row\[data-highlighted\]\s*\{([^}]*)\}/.exec(css);

    expect(highlighted?.[1]).toContain("outline: var(--state-focus-ring)");
    expect(highlighted?.[1]).toContain("calc(-1 * var(--state-focus-offset))");
  });
});
