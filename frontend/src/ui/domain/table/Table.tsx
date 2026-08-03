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
 * around the figure are the caller's, because `12 tasks` and `12 open · 3 at risk` are its sentence to write. */

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
}: TableProps<Row>) {
  return (
    <table className="table">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr>
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
        {rows.map((row) => (
          <tr key={rowKey(row)} className="state-row table__row">
            {columns.map((column) => (
              <td key={column.key} className={bodyCell({ measure: column.measure })}>
                {column.cell(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
      {countLabel === undefined ? null : (
        <tfoot>
          <tr>
            <td className="table__footer" colSpan={columns.length}>
              {countLabel(rows.length)}
            </td>
          </tr>
        </tfoot>
      )}
    </table>
  );
}
