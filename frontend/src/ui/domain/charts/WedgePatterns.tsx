/* THE PIE'S HATCH PATTERNS, ONE PER PIGMENT THE COMPOSITION DRAWS.
 *
 * A pie is SVG so that each wedge can carry its OWN texture, which is what a single HTML element with one
 * background cannot do: the wedges overlap in space and each needs a different pattern in the same box.
 *
 * A PATTERN CARRIES ITS OWN GROUND, so a wedge is one path with one fill. The alternative was two paths per
 * wedge, an ink one under a texture one, which doubles the geometry and gives a rounding error somewhere to
 * show through.
 *
 * ONE PATTERN PER PIGMENT, NOT PER WEDGE. A texture belongs to a step of the ramp rather than to a wedge, and
 * no two Areas hold one step, so a composition needs at most one tile per step it draws. */

import { HATCH_GEOMETRY, hatchFor, patternRotation, distinctPigments } from "./hatch";
import { chartPaint } from "./paint";
import type { ChartPigment } from "./series";

/** The vacancy's tile, which carries a ground and no lines. Its size is arbitrary and its content is not. */
const FLAT_TILE = 5;

/** How far a line is drawn past its tile, so a butt cap leaves no gap where two tiles meet. */
const OVERDRAW = 1;

export interface WedgePatternsProps {
  /** Unique within the document, so two pies on one screen cannot reference each other's patterns. */
  readonly idPrefix: string;
  readonly pigments: readonly ChartPigment[];
}

/** The id a wedge references its pattern by. Shared with the pie so the two cannot spell it differently. */
export function patternId(idPrefix: string, pigment: ChartPigment): string {
  return `${idPrefix}-${pigment}`;
}

export function WedgePatterns({ idPrefix, pigments }: WedgePatternsProps) {
  return (
    <defs>
      {distinctPigments(pigments).map((pigment) => {
        const hatch = hatchFor(pigment);
        const geometry = hatch === null ? null : HATCH_GEOMETRY[hatch];
        const pitch = geometry?.pitch ?? FLAT_TILE;
        return (
          <pattern
            key={pigment}
            id={patternId(idPrefix, pigment)}
            patternUnits="userSpaceOnUse"
            width={pitch}
            height={pitch}
            {...(geometry?.kind === "stripes"
              ? { patternTransform: `rotate(${patternRotation(geometry.angles[0])})` }
              : {})}
          >
            <rect
              className={chartPaint(pigment, "pie__hatch-ground")}
              width={pitch}
              height={pitch}
            />
            {geometry?.kind === "dots" && (
              <circle
                className={chartPaint(pigment, "pie__hatch-dot")}
                cx={pitch / 2}
                cy={pitch / 2}
                r={geometry.radius}
              />
            )}
            {geometry?.kind === "stripes" && (
              <line
                className={chartPaint(pigment, "pie__hatch-line")}
                x1={geometry.lineWidth / 2}
                y1={-OVERDRAW}
                x2={geometry.lineWidth / 2}
                y2={pitch + OVERDRAW}
                strokeWidth={geometry.lineWidth}
              />
            )}
            {/* The cross is two perpendicular families, so its tile holds the second line and one rotation
                carries both. `hatch.test.ts` asserts the two angles the token declares are perpendicular. */}
            {geometry?.kind === "stripes" && geometry.angles.length > 1 && (
              <line
                className={chartPaint(pigment, "pie__hatch-line")}
                x1={-OVERDRAW}
                y1={geometry.lineWidth / 2}
                x2={pitch + OVERDRAW}
                y2={geometry.lineWidth / 2}
                strokeWidth={geometry.lineWidth}
              />
            )}
          </pattern>
        );
      })}
    </defs>
  );
}
