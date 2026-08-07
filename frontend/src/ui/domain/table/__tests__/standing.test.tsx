/* A ROW'S STANDING: THE TWO STATES, THEIR TWO CHANNELS, AND EVERY COMBINATION OF THEM.
 *
 * The design language records why a matrix rather than four separate assertions: in the inherited language four
 * plausible state systems each looked correct on a single state and produced two pixel-identical rows in a
 * combination matrix while meaning different things. Overdue and at risk are the pair most likely to fall into
 * that hole, because they CO-OCCUR by construction rather than by coincidence: capacity is clipped to now, so a
 * task whose deadline has passed and still owes work has no capacity before it and the verdict names it too.
 *
 * SO THE MATRIX IS THE POINT. Each of the four combinations has to resolve to declarations of its own, which is
 * what proves the two states took two channels rather than one. `signatureOf` reads the real stylesheets and
 * matches them against the real element, because jsdom applies no stylesheet and a `getComputedStyle` assertion
 * would pass whether the rule existed or not.
 *
 * HOVER IS IN THE MATRIX TOO. It is the state that erases a fill, and the reason at risk is a mark rather than a
 * background: a reader running a pointer down the table must not lose the marking under their own cursor. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { kitStylesheets } from "../../../../testing/kitStylesheets";
import { signatureOf } from "../../../../testing/visualState";
import { Table, type TableColumn } from "../Table";

interface Task {
  readonly id: string;
  readonly title: string;
  readonly isOverdue: boolean;
  readonly isAtRisk: boolean;
}

const COLUMNS: readonly TableColumn<Task>[] = [
  { key: "title", header: "Task", cell: (task) => task.title },
];

const ORDINARY: Task = { id: "1", title: "Read one paper", isOverdue: false, isAtRisk: false };
const AT_RISK: Task = { id: "2", title: "Kontron take-home", isOverdue: false, isAtRisk: true };
const OVERDUE: Task = { id: "3", title: "Renew the visa", isOverdue: true, isAtRisk: false };
const BOTH: Task = { id: "4", title: "Tax return", isOverdue: true, isAtRisk: true };

function renderRows(rows: readonly Task[]) {
  return render(
    <Table
      caption="Open tasks"
      columns={COLUMNS}
      rowKey={(task) => task.id}
      rows={rows}
      standing={(task) => ({ isOverdue: task.isOverdue, isAtRisk: task.isAtRisk })}
    />,
  );
}

/** The row holding a given title, found by the cell the caller's column drew. */
function rowOf(title: string): HTMLElement {
  const row = screen.getByText(title, { selector: ".table__cell" }).closest("tr");
  if (row === null) throw new Error(`${title} is in no row`);
  return row;
}

describe("the standing a row carries", () => {
  it("marks each state with its own attribute from the closed vocabulary", () => {
    renderRows([ORDINARY, AT_RISK, OVERDUE, BOTH]);

    expect(rowOf("Read one paper")).not.toHaveAttribute("data-at-risk");
    expect(rowOf("Read one paper")).not.toHaveAttribute("data-overdue");
    expect(rowOf("Kontron take-home")).toHaveAttribute("data-at-risk");
    expect(rowOf("Kontron take-home")).not.toHaveAttribute("data-overdue");
    expect(rowOf("Renew the visa")).toHaveAttribute("data-overdue");
    expect(rowOf("Renew the visa")).not.toHaveAttribute("data-at-risk");
    expect(rowOf("Tax return")).toHaveAttribute("data-overdue");
    expect(rowOf("Tax return")).toHaveAttribute("data-at-risk");
  });

  /* The mark is decorative and the words behind it are not, so a reader who cannot see the glyph still hears
     which of the two the row is. */
  it("says the standing in words for a reader who cannot see the mark", () => {
    renderRows([ORDINARY, AT_RISK, OVERDUE, BOTH]);

    expect(screen.getByText("at risk")).toBeInTheDocument();
    expect(screen.getByText("overdue")).toBeInTheDocument();
    expect(screen.getByText("overdue and at risk")).toBeInTheDocument();
  });

  it("reserves the mark cell on every row, so becoming at risk changes a glyph and not a width", () => {
    const { container } = renderRows([ORDINARY, AT_RISK]);

    expect(container.querySelectorAll("tbody .state-mark")).toHaveLength(2);
    expect(container.querySelectorAll("thead .table__mark")).toHaveLength(1);
  });

  it("draws no mark column at all for a table whose rows have no standing", () => {
    const { container } = render(
      <Table caption="Day shapes" columns={COLUMNS} rowKey={(task) => task.id} rows={[ORDINARY]} />,
    );

    expect(container.querySelector(".table__mark")).toBeNull();
    expect(container.querySelectorAll("thead th")).toHaveLength(1);
  });

  it("spans the mark column in the footer, so the count sits under the whole table", () => {
    const { container } = render(
      <Table
        caption="Open tasks"
        columns={COLUMNS}
        countLabel={(count) => `${count} open`}
        rowKey={(task) => task.id}
        rows={[ORDINARY]}
        standing={(task) => ({ isOverdue: task.isOverdue, isAtRisk: task.isAtRisk })}
      />,
    );

    expect(container.querySelector("tfoot td")).toHaveAttribute(
      "colspan",
      String(COLUMNS.length + 1),
    );
  });

  it("spans only the caller's columns where there is no mark column to cover", () => {
    const { container } = render(
      <Table
        caption="Day shapes"
        columns={COLUMNS}
        countLabel={(count) => `${count} open`}
        rowKey={(task) => task.id}
        rows={[ORDINARY]}
      />,
    );

    expect(container.querySelector("tfoot td")).toHaveAttribute("colspan", String(COLUMNS.length));
  });
});

interface RowState {
  readonly isHovered: boolean;
  readonly isOverdue: boolean;
  readonly isAtRisk: boolean;
}

function combinations(): RowState[] {
  const states: RowState[] = [];
  for (const isHovered of [false, true]) {
    for (const isOverdue of [false, true]) {
      for (const isAtRisk of [false, true]) states.push({ isHovered, isOverdue, isAtRisk });
    }
  }
  return states;
}

function nameOf(state: RowState): string {
  const parts = [
    state.isHovered ? "hover" : null,
    state.isOverdue ? "overdue" : null,
    state.isAtRisk ? "at-risk" : null,
  ].filter((part) => part !== null);
  return parts.length === 0 ? "rest" : parts.join("+");
}

/** The row and its own mark slot, which is where the glyph-slot channel lands. */
function renderRow(state: RowState): { readonly row: Element; readonly slot: Element } {
  const { container } = render(
    <table>
      <tbody>
        <tr
          className="state-row table__row"
          data-overdue={state.isOverdue ? "" : undefined}
          data-at-risk={state.isAtRisk ? "" : undefined}
        >
          <td className="table__cell table__mark">
            <span aria-hidden="true" className="glyph state-mark" />
            <span className="sr-only">{nameOf(state)}</span>
          </td>
        </tr>
      </tbody>
    </table>,
  );
  const row = container.querySelector("tr");
  const slot = container.querySelector(".state-mark");
  if (row === null || slot === null) throw new Error("no row rendered");
  return { row, slot };
}

describe("the standing's states, in every combination", () => {
  async function signatures(): Promise<Map<string, string>> {
    const css = await kitStylesheets("states.css", "glyphs.css");
    const found = new Map<string, string>();
    for (const state of combinations()) {
      const active = state.isHovered ? [":hover"] : [];
      const { row, slot } = renderRow(state);
      /* Both elements are read, because the two channels land on two elements: the left rule on the row and
         the mark on its slot. A signature over the row alone would report the mark as nothing at all. */
      found.set(
        nameOf(state),
        `${signatureOf({ element: row, css, active })} || ${signatureOf({ element: slot, css, active })}`,
      );
    }
    return found;
  }

  it("renders all eight, so the matrix is a matrix", async () => {
    expect((await signatures()).size).toBe(8);
  });

  it("gives every combination a result of its own, with no collision to document", async () => {
    const found = await signatures();
    const bySignature = new Map<string, string[]>();
    for (const [name, signature] of found) {
      bySignature.set(signature, [...(bySignature.get(signature) ?? []), name]);
    }

    expect([...bySignature.values()].filter((group) => group.length > 1)).toEqual([]);
  });

  /* The whole reason at risk is a mark and not a fill: hover spends the fill, so a marking that used it would
     disappear under the reader's own pointer on the one row they were looking at. */
  it("keeps the at-risk mark under hover, and keeps the overdue rule too", async () => {
    const found = await signatures();
    const withMark = [...found.entries()].filter(([name]) => name.includes("at-risk"));
    const withRule = [...found.entries()].filter(([name]) => name.includes("overdue"));

    expect(withMark).toHaveLength(4);
    expect(withMark.filter(([, signature]) => signature.includes("--glyph:"))).toHaveLength(4);
    expect(withRule).toHaveLength(4);
    expect(
      withRule.filter(([, signature]) =>
        signature.includes("border-left-color: var(--state-overdue-color)"),
      ),
    ).toHaveLength(4);
  });

  /* Two channels, stated as an assertion rather than as a comment: the overdue rule is absent from a row that
     is only at risk, and the mark is absent from a row that is only overdue. One channel carrying both would
     fail exactly here. */
  it("spends one channel per state, so neither can erase the other", async () => {
    const found = await signatures();

    expect(found.get("at-risk")).not.toContain("border-left-color: var(--state-overdue-color)");
    expect(found.get("overdue")).not.toContain("--glyph:");
    expect(found.get("overdue+at-risk")).toContain("border-left-color: var(--state-overdue-color)");
    expect(found.get("overdue+at-risk")).toContain("--glyph:");
  });
});
