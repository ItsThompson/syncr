/* Fixture: a variant map, so a rule cannot be dodged by moving a utility off the element. */

import { cva } from "class-variance-authority";

export const button = cva("h-control px-3.25", {
  variants: {
    rank: {
      primary: "bg-ink text-on-ink transition-all",
      ghost: "bg-paper text-ink rounded-lg",
    },
  },
});
