/* Turning the review's categories into what each chart is handed.
 *
 * A chart takes already-computed quantities and already-formatted figures, so the arithmetic that turns a
 * category into a wedge belongs here, on the screen that read it. This is the one place a category becomes a
 * pigment, so the pie, the legend and the trend cannot disagree about which ink an Area holds.
 *
 * THE VACANCY IS A CATEGORY, NOT AN ABSENCE. The one row carrying no `areaId` is discretionary time no
 * confirmed block covered. It takes the kit's own `UNALLOCATED` pigment, which holds no step of the ramp and
 * therefore no hatch: Area redundancy is the only chart use of a texture, and the vacancy has no identity for
 * a texture to be redundant about.
 *
 * A DEVIATION ROW IS BUILT FROM SHARES, NOT FROM MINUTES, because the chart's own question is "how far off
 * target in percentage points". `DeviationRow` carries no pigment field at all, which is what makes the
 * cobalt-only rule a typecheck rather than a review comment.
 *
 * AN AREA THE LIST HAS NOT YET DELIVERED STILL DRAWS, AND NEVER AS THE VACANCY. The categories and the Area
 * names arrive from two reads, so declaring an Area leaves one redraw in which the review has a row the list
 * has no name for. Such a row takes a ramp step from its position and its identifier's short form as a label:
 * it is a real Area holding a real step, and painting it with the vacancy's ink would say the opposite of what
 * is true. The step it holds is dealt to it alone, because no two Areas are ever dealt one step.
 *
 * A WEDGE LABEL IS BOUNDED AND A LEGEND ROW IS NOT, because they sit in different boxes. The pie draws its
 * labels in a fixed gutter beside the circle; a legend row is a table cell that wraps. Measured in Chrome: the
 * gutter holds 97px and the label face sets at 5.7px per character, so a name past seventeen characters runs
 * out of the svg and paints over the panel's own border. An Area name may be sixty characters, so this is an
 * ordinary declaration rather than an edge case. THE LEGEND IS WHERE THE NAME IS CARRIED IN FULL, which is
 * also where the figure is, so nothing is lost: the wedge is identified beside the pie and named under it. */

import { areaPigment, UNALLOCATED } from "../../ui/domain";
import { asHours, asPercent, shareOf } from "./figures";
import type { AreaLegendEntry, AreaQuantity, ChartPigment, DeviationRow } from "../../ui/domain";
import type { Area } from "../../api/hooks/useAreas";
import type { ReviewCategory } from "../../api/hooks/useBudgetReview";

/** What the vacancy is called everywhere it appears: a wedge, a legend row, a deviation row. */
export const VACANCY_LABEL = "Unallocated";

/** How many characters of an identifier stand in for an Area whose name has not arrived. */
const SHORT_ID = 8;

export interface CategoryNaming {
  readonly label: string;
  readonly pigment: ChartPigment;
}

/** The key a category renders under, which is its Area or the one vacancy. */
export function keyOf(category: ReviewCategory): string {
  return category.areaId ?? UNALLOCATED;
}

/** What a category is called and painted with. The vacancy holds no Area, so it holds no ramp step. */
export function namingOf(
  category: ReviewCategory,
  areas: readonly Area[],
  index: number,
): CategoryNaming {
  if (category.areaId === null) return { label: VACANCY_LABEL, pigment: UNALLOCATED };
  const found = areas.find((area) => area.id === category.areaId);
  if (found === undefined) {
    return { label: category.areaId.slice(0, SHORT_ID), pigment: areaPigment(index) };
  }
  return { label: found.name, pigment: areaPigment(found.pigmentIndex) };
}

/** How many characters the pie's label gutter holds. Measured in Chrome: 97px at 5.7px per character. */
export const WEDGE_LABEL_CHARS = 17;

/** U+2026 HORIZONTAL ELLIPSIS, one glyph, so a bounded label spends one character rather than three. */
const ELLIPSIS = "\u2026";

/**
 * A category's name as a wedge label, bounded to what the pie's gutter holds.
 *
 * A name that fits is untouched. One that does not keeps its head and takes an ellipsis, and the legend row
 * beside the pie carries it in full: identity rests on the name, and the name is still there, in the one place
 * on this screen that has a column wide enough for it.
 */
export function wedgeLabel(name: string): string {
  if (name.length <= WEDGE_LABEL_CHARS) return name;
  return `${name.slice(0, WEDGE_LABEL_CHARS - 1).trimEnd()}${ELLIPSIS}`;
}

/** The pie's wedges, in the order the api drew them: each Area, then the vacancy. */
export function wedgesOf(
  categories: readonly ReviewCategory[],
  areas: readonly Area[],
): readonly AreaQuantity[] {
  return categories.map((category, index) => {
    const naming = namingOf(category, areas, index);
    return {
      id: keyOf(category),
      ...naming,
      label: wedgeLabel(naming.label),
      minutes: category.actualMinutes,
    };
  });
}

/** The legend beside the pie: a chip, the name, and the share of discretionary time. */
export function legendOf(
  categories: readonly ReviewCategory[],
  areas: readonly Area[],
  discretionaryMinutes: number | null,
): readonly AreaLegendEntry[] {
  return categories.map((category, index) => ({
    id: keyOf(category),
    ...namingOf(category, areas, index),
    figure: asPercent(shareOf(category.actualMinutes, discretionaryMinutes)),
  }));
}

/**
 * The deviation rows: actual share against target share, in percentage points.
 *
 * A category with no target is left out. That is a week with no plan of record, where every row would compare
 * a figure against nothing; the panel states that instead, which is what a period with absent figures needs
 * rather than a chart of zeros.
 */
export function deviationRowsOf(
  categories: readonly ReviewCategory[],
  areas: readonly Area[],
  discretionaryMinutes: number | null,
): readonly DeviationRow[] {
  return categories.reduce<DeviationRow[]>((rows, category, index) => {
    if (category.targetMinutes === null) return rows;
    rows.push({
      id: keyOf(category),
      label: namingOf(category, areas, index).label,
      actual: shareOf(category.actualMinutes, discretionaryMinutes),
      target: shareOf(category.targetMinutes, discretionaryMinutes),
    });
    return rows;
  }, []);
}

/** The hours a category held, as the Area table's `This week` cell reads it. */
export function hoursOf(category: ReviewCategory | undefined): string {
  return asHours(category?.actualMinutes ?? 0);
}
