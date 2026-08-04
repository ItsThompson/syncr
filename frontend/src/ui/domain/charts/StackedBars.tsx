/* TREND OVER TIME: stacked bars by week, in Area ink, hatched.
 *
 * THERE IS NO LINE CHART IN THIS PRODUCT AND THIS COMPONENT IS WHY. The Area ramp is sealed to two chart
 * carriers, a pie wedge fill and a stacked bar fill, so a time series drawn as a line has no legal ink: a line is
 * neither of them. Twelve cobalt lines separated only by dash pattern is unreadable, so the answer is not to
 * find a colour for a line, it is not to draw one. `__tests__/charts.test.tsx` asserts this family exports no
 * line chart and that no source here draws a polyline, because a rule with no check is a rule that arrives back
 * in six months.
 *
 * EACH BAR IS NORMALISED TO ITS OWN TOTAL, so the reading is composition per week rather than volume per week.
 * A week that held less time still fills its bar, and its label states the week. Volume is the deviation chart's
 * question.
 *
 * A SEGMENT PAIRS ITS PIGMENT WITH A HATCH, always on, in a lighter step of its own ink. The texture comes
 * straight from the token layer's gradients here: a background-image is exactly the shape those tokens are, so
 * nothing about the six patterns is restated in this file.
 *
 * EACH BAR STATES ITS OWN COMPOSITION IN WORDS. A pie has a legend beside it carrying every category and its
 * figure; a trend has no such column, so the shares reach a screen reader from the bar itself or not at all. */

import { chartPaint } from "./paint";
import type { AreaQuantity, StackedBar } from "./series";
import "./charts.css";

const PERCENT = 100;
/** Two decimals, so a segment's width cannot round a whole bar past 100%. */
const PLACES = 2;

export interface StackedBarsProps {
  readonly bars: readonly StackedBar[];
  readonly caption: string;
}

function drawableSegments(bar: StackedBar): readonly AreaQuantity[] {
  return bar.segments.filter((segment) => segment.minutes > 0);
}

/** What a screen reader hears in place of the bar: the week, then each category and its whole-percent share.
 *
 * EACH SHARE IS ROUNDED ON ITS OWN, so a spoken list can sum to 99% or 101%. That is deliberate: a reader hears
 * the shares one at a time rather than adding them, and redistributing a remainder would make an Area's spoken
 * share disagree with the same Area's figure in the legend beside it, which is the worse of the two. */
function spokenComposition(
  bar: StackedBar,
  segments: readonly AreaQuantity[],
  total: number,
): string {
  const shares = segments.map(
    (segment) => `${segment.label} ${Math.round((segment.minutes / total) * PERCENT)}%`,
  );
  return `${bar.label}: ${shares.join(", ")}`;
}

export function StackedBars({ bars, caption }: StackedBarsProps) {
  const drawable = bars.filter((bar) => drawableSegments(bar).length > 0);

  return (
    <figure className="chart">
      <figcaption className="chart__caption">{caption}</figcaption>
      {drawable.length === 0 ? (
        <p className="chart__nothing">
          No week in this period holds any time, so there is no trend to draw.
        </p>
      ) : (
        drawable.map((bar) => {
          const segments = drawableSegments(bar);
          const total = segments.reduce((sum, segment) => sum + segment.minutes, 0);
          return (
            <div key={bar.id} className="stacked__row">
              <span className="stacked__label">{bar.label}</span>
              <span
                className="stacked__track"
                role="img"
                aria-label={spokenComposition(bar, segments, total)}
              >
                {segments.map((segment) => (
                  <span
                    key={segment.id}
                    className={chartPaint(
                      segment.pigment,
                      "stacked__segment chart-fill chart-fill--hatched",
                    )}
                    style={{ width: `${((segment.minutes / total) * PERCENT).toFixed(PLACES)}%` }}
                  />
                ))}
              </span>
            </div>
          );
        })
      )}
    </figure>
  );
}
