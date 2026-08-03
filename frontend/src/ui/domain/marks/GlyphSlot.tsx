/* The glyph slot: one small space, and whichever of its four occupants claims it.
 *
 * A COMPONENT NAMES A SLOT AND NEVER A MARK. Every mark in the product is written once, as a codepoint, in
 * `ui/primitives/glyphs.css`, and reaches an element as generated content. That is what makes a collision
 * detectable by reading one file, and it is also what makes a mark survive forced-colors mode, where a fill is
 * dropped and generated content is not.
 *
 * THE MARK IS DECORATIVE TO A SCREEN READER. A pinned block says it is pinned in its own accessible name, and
 * the blocks staggered behind an overlapping one are in the document to be traversed: a reader who hears the
 * marks as well hears each block twice. */

import { cva } from "class-variance-authority";

import "../../primitives/glyphs.css";
import "./marks.css";
import { glyphSlotOccupant, type GlyphSlotClaim } from "./occupant";

/* One axis with ten values, because the slot holds exactly one mark: the precedence picks the occupant and
 * this maps it onto the slot class that reaches the table. */
const slot = cva("glyph glyph-slot", {
  variants: {
    occupant: {
      pinned: "glyph--pinned",
      overlap: "glyph--overlap",
      "proposal-source": "glyph--proposal-source",
      frame: "glyph--origin-frame",
      template_entry: "glyph--origin-template-entry",
      habit: "glyph--origin-habit",
      task: "glyph--origin-task",
      anchor: "glyph--origin-anchor",
      prep: "glyph--origin-prep",
      transit: "glyph--origin-transit",
    },
  },
});

export type GlyphSlotProps = GlyphSlotClaim;

export function GlyphSlot(claim: GlyphSlotProps) {
  const occupant = glyphSlotOccupant(claim);
  if (occupant === null) return null;

  return (
    <span className={slot({ occupant })} aria-hidden="true">
      {occupant === "overlap" ? claim.overlapCount : null}
    </span>
  );
}
