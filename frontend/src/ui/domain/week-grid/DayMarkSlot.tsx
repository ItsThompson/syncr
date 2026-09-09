import { cva } from "class-variance-authority";

import "../../primitives/glyphs.css";

import type { DayMark } from "./types";

export interface DayMarkSlotProps {
  readonly marks: readonly DayMark[];
}

const slot = cva("glyph week-day__mark", {
  variants: {
    pigment: {
      info: "week-day__mark--info glyph--notice-info",
      amber: "week-day__mark--amber glyph--notice-attention",
    },
  },
});

/** The one mark a header can show. Amber takes precedence over informational conditions. */
export function dayHeaderMarkOf(marks: readonly DayMark[]): DayMark | null {
  return marks.find((mark) => mark.pigment === "amber") ?? marks.at(0) ?? null;
}

export function DayMarkSlot({ marks }: DayMarkSlotProps) {
  const mark = dayHeaderMarkOf(marks);
  if (mark === null) return null;

  return <span aria-hidden="true" className={slot({ pigment: mark.pigment })} />;
}
