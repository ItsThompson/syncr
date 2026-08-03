/* The notice's surface: its volume and its pigment, mapped onto classes in one place.
 *
 * Three volume components read this rather than each assembling its own class list. Written as a variant map
 * because that is the shape the markup scan can read: a class assembled from a template literal, `notice--${p}`,
 * reaches an element with the interpolated half invisible to the layer 0 rule, the arbitrary-value rule and the
 * radius rule alike, and `lint:markup` refuses that shape for exactly this reason. */

import { cva } from "class-variance-authority";

import type { NoticePigment } from "./notice";

export const noticeSurface = cva("notice", {
  variants: {
    volume: {
      inline: "notice--inline",
      panel: "notice--panel",
      banner: "notice--banner",
    },
    pigment: {
      info: "notice--info",
      amber: "notice--amber",
      oxide: "notice--oxide",
      verdigris: "notice--verdigris",
    },
  },
});

/**
 * Whether a screen reader interrupts for this notice.
 *
 * Oxide is the only kind where something is broken, so it is the only one that interrupts. Derived from the
 * pigment rather than passed, because the two cannot then disagree about whether a notice is a failure.
 */
export function noticeRole(pigment: NoticePigment): "alert" | "status" {
  return pigment === "oxide" ? "alert" : "status";
}
