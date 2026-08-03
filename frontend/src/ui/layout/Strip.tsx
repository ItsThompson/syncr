/* A horizontal band: the top bar, the summary strip above the week grid, and a readout row.
 *
 * The height is a variant rather than a caller's class, because it is a named design decision: the summary
 * strip's height is reserved so the grid beneath it cannot shift mid-drag, and a readout row's is not. */

import type { ReactNode } from "react";
import { cva } from "class-variance-authority";

import "./Strip.css";

const strip = cva("strip", {
  variants: {
    height: {
      auto: "",
      fixed: "strip--fixed",
    },
  },
  defaultVariants: { height: "auto" },
});

export interface StripProps {
  readonly children: ReactNode;
  /** `fixed` reserves --strip-h, so nothing below the band moves when its content arrives. */
  readonly height?: "auto" | "fixed" | undefined;
}

export function Strip({ children, height }: StripProps) {
  return <div className={strip({ height })}>{children}</div>;
}
