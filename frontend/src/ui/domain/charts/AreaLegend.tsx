/* THE CHART LEGEND: a chip, the Area's NAME, and the figure.
 *
 * THE CHIP IS NEVER SHOWN WITHOUT THE NAME. A chip on its own encodes a category in colour alone, which roughly
 * one man in twelve cannot read, and three of the ramp's pigments sit on the sealed signal hues by construction.
 * The name is a required member of an entry, so a nameless chip fails the typecheck. It is required rather than
 * non-empty: `label: ""` still renders a bare chip, which is the same reach `AreaChip` has.
 *
 * THE CHIP CARRIES NO HATCH, and that is the one carrier rule at work rather than an omission. One carrier per
 * context, never two at once: a chip IS the ledger carrier, and the name beside it is a stronger redundancy than
 * any texture. `docs/design/components.html` draws its legend row with a hatched swatch AND a chip, which is two
 * Area carriers in one row; the kit follows its own component inventory instead, which says chip plus name plus
 * figure.
 *
 * A CATEGORY HOLDING NOTHING KEEPS ITS ROW. A zero-hour Area cannot be drawn as a wedge, and dropping it from
 * the legend would hide what the period did not hold, which is the whole point of the review. */

import { chartPaint } from "./paint";
import type { AreaLegendEntry } from "./series";
import "./charts.css";

export interface AreaLegendProps {
  readonly entries: readonly AreaLegendEntry[];
  /** Names the list, which is what a screen reader announces before the first row. */
  readonly label: string;
}

export function AreaLegend({ entries, label }: AreaLegendProps) {
  /* Nothing at all rather than a labelled empty list: the chart beside it already states that the period holds
   * no category, and saying it twice in two registers is worse than saying it once. */
  if (entries.length === 0) return null;

  return (
    <ul className="legend" aria-label={label}>
      {entries.map((entry) => (
        <li key={entry.id} className="legend__entry">
          {/* Decorative: the name beside it identifies the category, and announcing both reads it twice. */}
          <span className={chartPaint(entry.pigment, "area-chip chart-fill")} aria-hidden="true" />
          <span className="legend__name">{entry.label}</span>
          <span className="legend__figure">{entry.figure}</span>
        </li>
      ))}
    </ul>
  );
}
