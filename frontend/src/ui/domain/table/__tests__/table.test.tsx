/* THE TABLE'S FOUR CLAIMS, AND WHERE EACH IS ASSERTED.
 *
 * 28px rows and --fs-data cells are the stylesheet's, so they are read from it: jsdom applies no stylesheet, and a
 * rendered assertion about a row's height would pass whether the rule exists or not. The sortable header and the
 * footer count are behaviour, so they are exercised through the rendering. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { Table, type TableColumn, type TableSort } from "../Table";

interface Task {
  readonly id: string;
  readonly title: string;
  readonly minutes: number;
}

const TASKS: readonly Task[] = [
  { id: "1", title: "Leetcode · Graphs", minutes: 90 },
  { id: "2", title: "36 South application", minutes: 45 },
  { id: "3", title: "Topic list questions", minutes: 60 },
];

const COLUMNS: readonly TableColumn<Task>[] = [
  { key: "title", header: "Task", cell: (task) => task.title, isSortable: true },
  {
    key: "minutes",
    header: "Estimate",
    measure: "figure",
    isSortable: true,
    cell: (task) => task.minutes,
  },
];

function renderTable(props: Partial<Parameters<typeof Table<Task>>[0]> = {}) {
  const onSortChange = vi.fn<(next: TableSort) => void>();
  const result = render(
    <Table
      columns={COLUMNS}
      rows={TASKS}
      rowKey={(task) => task.id}
      caption="Open tasks"
      onSortChange={onSortChange}
      countLabel={(count) => `${count} open`}
      {...props}
    />,
  );
  return { onSortChange, ...result };
}

const stylesheet = () => kitStylesheet("table/table.css", domainDir);

describe("the table's rows", () => {
  it("are named by a caption a screen reader reads before them", () => {
    renderTable();

    expect(screen.getByRole("table", { name: "Open tasks" })).toBeInTheDocument();
  });

  it("render every row the caller passed, in the order it passed them", () => {
    const { container } = renderTable();
    const cells = [...container.querySelectorAll("tbody td")].map((cell) => cell.textContent);

    expect(cells).toEqual([
      "Leetcode · Graphs",
      "90",
      "36 South application",
      "45",
      "Topic list questions",
      "60",
    ]);
  });

  it("pitch at --h-row with cells at --fs-data, which is the step for numbers you compare", async () => {
    const css = await stylesheet();

    expect(/\.table__row\s*\{[^}]*height:\s*var\(--h-row\)/.test(css)).toBe(true);
    expect(/\.table\s*\{[^}]*font-size:\s*var\(--fs-data\)/.test(css)).toBe(true);
  });

  it("set their figures tabular, so a column of them lines up", async () => {
    const css = await stylesheet();

    expect(/\.table\s*\{[^}]*font-variant-numeric:\s*tabular-nums/.test(css)).toBe(true);
  });

  it("right-align a figure column and leave a text column alone", () => {
    renderTable();
    const [title, estimate] = screen.getAllByRole("columnheader");

    expect(title).not.toHaveClass("table__header--figure");
    expect(estimate).toHaveClass("table__header--figure");
  });
});

describe("the sortable header", () => {
  it("is a control rather than a click handler on a cell, so a keyboard reaches it", () => {
    renderTable();

    expect(screen.getByRole("button", { name: /Task/ })).toBeInTheDocument();
  });

  it("asks for the column ascending when the rows are ordered by another", async () => {
    const { onSortChange } = renderTable({ sort: { key: "minutes", direction: "ascending" } });

    await userEvent.click(screen.getByRole("button", { name: /Task/ }));

    expect(onSortChange).toHaveBeenCalledWith({ key: "title", direction: "ascending" });
  });

  it("reverses the column the rows are already ordered by", async () => {
    const { onSortChange } = renderTable({ sort: { key: "title", direction: "ascending" } });

    await userEvent.click(screen.getByRole("button", { name: /Task/ }));

    expect(onSortChange).toHaveBeenCalledWith({ key: "title", direction: "descending" });
  });

  /* `aria-sort` sits on the column the rows are ACTUALLY ordered by. Announcing it on the column a reader last
   * pressed while the rows run by another tells a screen reader something the table does not do. */
  it("announces the order on the ordered column, and none on the others", () => {
    renderTable({ sort: { key: "minutes", direction: "descending" } });
    const [title, estimate] = screen.getAllByRole("columnheader");

    expect(estimate).toHaveAttribute("aria-sort", "descending");
    expect(title).toHaveAttribute("aria-sort", "none");
  });

  it("draws the direction as a mark rather than as colour alone", () => {
    const { container } = renderTable({ sort: { key: "minutes", direction: "ascending" } });

    expect(container.querySelector(".table__direction.glyph--triangle-up")).not.toBeNull();
  });

  it("is inert without a handler, because a header that reports nowhere is a decoration", () => {
    renderTable({ onSortChange: undefined });

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getAllByRole("columnheader")[0]).not.toHaveAttribute("aria-sort");
  });
});

describe("the footer count", () => {
  it("is summed from the rows rendered, so the table cannot disagree with itself", () => {
    renderTable();

    expect(screen.getByText("3 open")).toBeInTheDocument();
  });

  it("is absent when the caller has no sentence to write", () => {
    const { container } = renderTable({ countLabel: undefined });

    expect(container.querySelector("tfoot")).toBeNull();
  });
});
