/* A hairline separator, horizontal or vertical.
 *
 * An `hr` rather than a styled `div`, because a separator is what an `hr` IS: a screen reader announces it,
 * and the vertical form keeps that meaning between two cells of a strip where a border on a neighbour would
 * announce nothing.
 *
 * Which ink it draws in is decided by the surface it lands on, in the stylesheet, so a caller never chooses. */

import { cva } from "class-variance-authority";

import "./Rule.css";

const rule = cva("rule", {
  variants: {
    orientation: {
      horizontal: "",
      vertical: "rule--vertical",
    },
  },
  defaultVariants: { orientation: "horizontal" },
});

export interface RuleProps {
  /** Vertical divides two cells in a row; horizontal divides two blocks in a column. */
  readonly orientation?: "horizontal" | "vertical" | undefined;
}

export function Rule({ orientation }: RuleProps) {
  return (
    <hr
      className={rule({ orientation })}
      aria-orientation={orientation === "vertical" ? "vertical" : undefined}
    />
  );
}
