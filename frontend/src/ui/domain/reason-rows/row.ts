/* WHAT A LABELLED ROW IS, AND WHY THE SET OF THEM IS NOT A PARAGRAPH.
 *
 * A reason record has a fixed schema: at most two rejected windows, exactly one dominant term, at most one
 * superseded placement. Rows imply that schema and a paragraph implies unbounded prose, so the shape of the
 * rendering is the shape of the data. It is also what makes a reason readable at a glance next to a grid: the label
 * column is the same width on every row and the eye reads down it.
 *
 * THE LABEL COLUMN IS A SHARED TOKEN, at --clause-label-w, because three sheets independently chose 60px, 64px and
 * 76px before it was one. The detail panel's definition rows read the same width from the same declaration, which
 * is why this component takes any labelled row rather than a `ReasonRecord`: `when`, `source`, `type` and
 * `authority` are the same rendering as `pinned`, `instead of` and `cost`, and two components for one form would be
 * two places for that width to drift. */

/** One row: what it is called, and what it says. Both already in the words a reader reads. */
export interface LabelledRow {
  /** The clause kind or the definition term, lowercase, as the design record renders it. */
  readonly label: string;
  readonly value: string;
}
