/* The table: 28px rows, --fs-data cells, tabular figures, a sortable header and a footer count.
 *
 * THE ROWS ARE THE CALLER'S, ALREADY IN ORDER. This component does not sort: which comparison is right for a
 * column of deadlines, of Areas or of confidence figures is a domain decision, and a table that sorted its own
 * rows would need to know all three. It reports the header a reader activated and renders what comes back, which
 * is also what lets a screen sort server-side without a second code path.
 *
 * `aria-sort` SITS ON THE COLUMN THE ROWS ARE ACTUALLY ORDERED BY, and on no other. Announcing it on the column a
 * reader last clicked while the rows are ordered by another tells a screen reader something the table does not do.
 *
 * THE FOOTER COUNT IS SUMMED FROM THE ROWS AT RENDER, so the table cannot disagree with its own footer. The words
 * around the figure are the caller's, because `12 tasks` and `12 open · 3 at risk` are its sentence to write.
 *
 * A ROW'S STANDING IS TWO STATES FROM THE CLOSED VOCABULARY, and the table takes them as a function of the row
 * rather than as a column, because they are states and not values: `overdue` takes the left rule and `at-risk`
 * takes the glyph slot, one channel each, so a row carrying both says both. Both are assigned once for the whole
 * kit under `ui/primitives`; what this component owns is the cell the mark sits in, reserved on every row so a row
 * becoming at risk changes a glyph rather than a width, and the words behind the mark for a reader who cannot see
 * it. Which rows carry which state is the caller's: whether a deadline has passed is arithmetic over a clock, and
 * whether the work fits before it is the server's determination. */

import type { ReactNode } from "react";
import { cva } from "class-variance-authority";

import "../../primitives/glyphs.css";
import "../../primitives/states.css";
import "./table.css";

const headerCell = cva("table__header", {
  variants: {
    measure: {
      text: "",
      figure: "table__header--figure",
    },
  },
  defaultVariants: { measure: "text" },
});

const bodyCell = cva("table__cell", {
  variants: {
    measure: {
      text: "",
      figure: "table__cell--figure",
    },
  },
  defaultVariants: { measure: "text" },
});

/* The mark is reserved on every sortable header, so ordering a column changes a glyph rather than a width. */
const direction = cva("glyph table__direction", {
  variants: {
    order: {
      ascending: "glyph--triangle-up",
      descending: "glyph--triangle-down",
      none: "",
    },
  },
});

export type TableMeasure = "text" | "figure";
export type SortDirection = "ascending" | "descending";

/**
 * What a row's standing is, in the closed vocabulary's own two words.
 *
 * Both may be true at once and the treatments compose, which is why they are two booleans rather than one
 * ordered standing: an overdue task that still owes work has no capacity before its own deadline, so the
 * verdict names it too, and a single value would have to drop one of the two facts.
 */
export interface TableRowStanding {
  /** The deadline has passed. */
  readonly isOverdue?: boolean | undefined;
  /** The server's determination that the work does not fit before the deadline. */
  readonly isAtRisk?: boolean | undefined;
}

/** What the reserved mark cell says to a reader who cannot see the mark. */
function standingWords(standing: TableRowStanding): string {
  const said = [
    standing.isOverdue === true ? "overdue" : null,
    standing.isAtRisk === true ? "at risk" : null,
  ].filter((part) => part !== null);
  return said.join(" and ");
}

export interface TableSort {
  readonly key: string;
  readonly direction: SortDirection;
}

export interface TableColumn<Row> {
  /** Identifies the column to the sort, and keys the cell. */
  readonly key: string;
  readonly header: string;
  /** A figure right-aligns, because a number is compared down a column. */
  readonly measure?: TableMeasure | undefined;
  /** Absent means the column cannot be ordered by. */
  readonly isSortable?: boolean | undefined;
  readonly cell: (row: Row) => ReactNode;
}

export interface TableProps<Row> {
  readonly columns: readonly TableColumn<Row>[];
  /** Already in the order they are to be drawn. */
  readonly rows: readonly Row[];
  readonly rowKey: (row: Row) => string;
  /** The table's accessible name, announced before its first row. */
  readonly caption: string;
  /** Which column the rows are ordered by, and which way. */
  readonly sort?: TableSort | undefined;
  /** Called with the order a header press asks for. Absent leaves every header inert. */
  readonly onSortChange?: ((next: TableSort) => void) | undefined;
  /** The footer's sentence, given the count of rows rendered. */
  readonly countLabel?: ((count: number) => string) | undefined;
  /**
   * Each row's standing. Absent leaves every row ordinary and draws no mark column at all.
   *
   * A function of the row rather than a field on it, so a table over a shape that has no standing does not
   * have to invent one, and so the two states stay the caller's determination.
   */
  readonly standing?: ((row: Row) => TableRowStanding) | undefined;
}

/** Pressing the ordered column reverses it; pressing another orders by it, ascending. */
function nextSort(key: string, sort: TableSort | undefined): TableSort {
  if (sort?.key !== key) return { key, direction: "ascending" };
  return { key, direction: sort.direction === "ascending" ? "descending" : "ascending" };
}

export function Table<Row>({
  columns,
  rows,
  rowKey,
  caption,
  sort,
  onSortChange,
  countLabel,
  standing,
}: TableProps<Row>) {
  const hasStanding = standing !== undefined;
  return (
    <table className="table">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr>
          {hasStanding ? (
            <th scope="col" className="table__header table__mark">
              <span className="sr-only">Standing</span>
            </th>
          ) : null}
          {columns.map((column) => {
            const order = sort?.key === column.key ? sort.direction : "none";
            const isSortable = column.isSortable === true && onSortChange !== undefined;
            return (
              <th
                key={column.key}
                scope="col"
                className={headerCell({ measure: column.measure })}
                aria-sort={isSortable ? order : undefined}
              >
                {isSortable ? (
                  <button
                    type="button"
                    className="table__sort"
                    onClick={() => onSortChange(nextSort(column.key, sort))}
                  >
                    {column.header}
                    <span className={direction({ order })} aria-hidden="true" />
                  </button>
                ) : (
                  column.header
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const said = standing === undefined ? {} : standing(row);
          return (
            <tr
              key={rowKey(row)}
              className="state-row table__row"
              data-overdue={said.isOverdue === true ? "" : undefined}
              data-at-risk={said.isAtRisk === true ? "" : undefined}
            >
              {hasStanding ? (
                <td className="table__cell table__mark">
                  <span className="glyph state-mark" aria-hidden="true" />
                  <span className="sr-only">{standingWords(said)}</span>
                </td>
              ) : null}
              {columns.map((column) => (
                <td key={column.key} className={bodyCell({ measure: column.measure })}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
      {countLabel === undefined ? null : (
        <tfoot>
          <tr>
            <td
              className="table__footer"
              colSpan={hasStanding ? columns.length + 1 : columns.length}
            >
              {countLabel(rows.length)}
            </td>
          </tr>
        </tfoot>
      )}
    </table>
  );
}
