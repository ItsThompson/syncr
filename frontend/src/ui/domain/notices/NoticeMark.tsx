/* The notice's mark: the second encoding of its kind, beside the pigment.
 *
 * COLOUR IS NEVER THE ONLY ENCODING OF ANYTHING, so a failure and a notice differ in shape as well as in
 * pigment. Two of the four marks are ones this kit already draws: a failure takes the cross, which the dialog's
 * dismiss control also draws, and a resolved notice takes the tick, which a checked box and a completed wizard
 * step draw. A mark shared by two meanings is one entry in the glyph table named after its shape, because a
 * second entry holding the same codepoint is the collision the table exists to prevent.
 *
 * The mark is decorative: the notice's own title says what kind of thing happened in words. */

import { cva } from "class-variance-authority";

import "../../primitives/glyphs.css";
import type { NoticePigment } from "./notice";

const mark = cva("glyph notice__mark", {
  variants: {
    pigment: {
      info: "glyph--notice-info",
      amber: "glyph--notice-attention",
      oxide: "glyph--cross",
      verdigris: "glyph--check",
    },
  },
});

export interface NoticeMarkProps {
  readonly pigment: NoticePigment;
}

export function NoticeMark({ pigment }: NoticeMarkProps) {
  return <span className={mark({ pigment })} aria-hidden="true" />;
}
