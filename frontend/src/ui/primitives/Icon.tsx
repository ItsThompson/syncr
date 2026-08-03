/* An icon: lucide at three sizes, drawn from the icon tokens.
 *
 * Standard lucide stroke weight at 14, 16 and 20, and nothing else. The three sizes are a closed set for
 * the same reason the type scale is: adding a step means naming the surface that needs it.
 *
 * The stroke, the caps and the joins are declared in `Icon.css` from --icon-stroke, --icon-cap and
 * --icon-join. lucide renders them as presentation attributes on the svg, and a presentation attribute
 * loses to a stylesheet declaration, so the tokens are what the browser draws. That indirection is the
 * point: hard-coding `strokeLinecap="round"` here is a review failure even though it produces the same
 * output today, because the inherited language's two reference sheets diverged once when its tokens were
 * silent on caps.
 *
 * An icon is decorative by default. In navigation it pairs with an uppercase tracked label, so the label
 * is what a screen reader reads. A caller that means the icon to be the only name for a control passes
 * `label`, which becomes the accessible name instead. */

import type { LucideIcon } from "lucide-react";
import type { Ref } from "react";
import { cva } from "class-variance-authority";

import "./Icon.css";

const icon = cva("icon", {
  variants: {
    size: {
      sm: "icon--sm",
      base: "",
      lg: "icon--lg",
    },
  },
  defaultVariants: { size: "base" },
});

export interface IconProps {
  /** A lucide component. The kit draws no icons of its own. */
  readonly mark: LucideIcon;
  /** 14, 16 or 20, read from --icon-sm, --icon and --icon-lg. */
  readonly size?: "sm" | "base" | "lg" | undefined;
  /**
   * The accessible name, when the icon is the only name a control has.
   *
   * Absent means decorative, which is the common case: an icon in navigation sits beside the label it
   * illustrates, and announcing both reads the row twice.
   */
  readonly label?: string | undefined;
  /** The drawn svg, which is what a caller measures when an icon has to line up with type. */
  readonly ref?: Ref<SVGSVGElement> | undefined;
}

export function Icon({ mark: Mark, size, label, ref }: IconProps) {
  return (
    <Mark
      ref={ref}
      className={icon({ size })}
      aria-hidden={label === undefined ? true : undefined}
      aria-label={label}
      role={label === undefined ? undefined : "img"}
    />
  );
}
