/* WHAT EACH COLUMN TAKES: a length it declares, or a share of what the lengths leave over.
 *
 * A TABLE THAT DECLARES NOTHING IS LAID OUT FROM ITS CONTENT, so the widest cell in a column widens that column
 * and narrows the ones beside it. A reader's columns then move as the rows change, and the same table is a
 * different shape on two screens. A declared policy is the alternative to that: the columns hold still, and a
 * cell too wide for its own column spends the height of its own row instead of its neighbours' width.
 *
 * THE ARITHMETIC IS THE BROWSER'S. A share is emitted as a `calc()` over the declared lengths rather than
 * resolved here, because those lengths are CSS the caller wrote and may be in any unit or name any custom
 * property: mixing units is what `calc` is for, and this module never has to know how wide `var(--w-sidebar)` is
 * beside `18px`.
 *
 * A COLUMN THAT DECLARES NOTHING, IN A TABLE WHERE SOMETHING DOES, claims one share. That is the equal division
 * the browser would have made of the same space, so a caller can adopt the policy one column at a time and the
 * columns it has said nothing about do not move.
 *
 * A LENGTH IS EXACT ONLY WHERE SOME COLUMN CLAIMS A SHARE. Every length is subtracted from the table's width and
 * the shares divide what is left, so a length renders at its own figure while one column absorbs the difference.
 * Give every column a length and no share is claimed: nothing absorbs, a fixed layout scales all of them to the
 * container, and lengths adding up past it overflow. This function emits what the caller declared either way. A
 * length a browser then scales is still the caller's declaration, and refusing it here would mean owning the unit
 * parser this module exists to avoid. `probe/table.probe.test.tsx` measures what the browser does with both. */

/** How wide a column is: a CSS length it takes, or a weight, which is its share of what the lengths leave over. */
export type TableColumnWidth = string | { readonly weight: number };

const ONE_SHARE = 1;

function isLength(width: TableColumnWidth | undefined): width is string {
  return typeof width === "string";
}

/**
 * The share of the surplus a column claims, which is none when it takes a length of its own.
 *
 * A weight is a positive share. A caller's zero or negative one claims nothing rather than dividing the surplus
 * by zero, which would emit a width no browser can resolve.
 */
function weightOf(width: TableColumnWidth | undefined): number {
  if (width === undefined) return ONE_SHARE;
  if (isLength(width)) return 0;
  return Math.max(width.weight, 0);
}

/**
 * One column's slice of the surplus, as an expression a browser resolves rather than this module.
 *
 * A sole claimant takes the surplus whole. `* 1 / 1` resolves to the same width, so that branch is for whoever
 * reads the expression in devtools and nothing turns on which shape it gets.
 */
function shareOf(surplus: string, weight: number, total: number): string {
  if (weight === 0) return "0px";
  if (weight === total) return `calc(${surplus})`;
  return `calc((${surplus}) * ${weight} / ${total})`;
}

/**
 * The width each column's `<col>` takes, in the order the columns are drawn, or null when none declares one.
 *
 * @param reserved lengths the table spends on columns that are not the caller's, which the surplus is net of.
 */
export function columnWidthsOf(
  declared: readonly (TableColumnWidth | undefined)[],
  reserved: readonly string[],
): readonly string[] | null {
  if (!declared.some((width) => width !== undefined)) return null;

  const total = declared.reduce((sum, width) => sum + weightOf(width), 0);
  const taken = [...reserved, ...declared.filter(isLength)];
  const surplus = taken.length === 0 ? "100%" : `100% - (${taken.join(" + ")})`;

  return declared.map((width) =>
    isLength(width) ? width : shareOf(surplus, weightOf(width), total),
  );
}
