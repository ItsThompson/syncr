/* The button, at four ranks.
 *
 * A rank is a named design decision, so it comes from `cva` rather than from a caller assembling classes.
 * The ranks are primary, secondary, tertiary and quiet, and a disabled button is a state of any of them
 * rather than a fifth rank.
 *
 * `asChild` renders the caller's own element with the button's shape, which is how a button that
 * NAVIGATES becomes a real link: an anchor with an href keeps middle-click, cmd-click and the browser's
 * own affordances, and a click handler assigning `window.location` keeps none of them.
 *
 * `isDisabled` sets both `disabled` and `aria-disabled`, because a disabled button that stays in the tab
 * order needs the ARIA form and a native one needs the attribute. Nothing here toggles a class. */

import type { ReactNode, Ref } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";

import "./Button.css";

const button = cva("button inline-flex items-center justify-center gap-2 font-mono", {
  variants: {
    rank: {
      primary: "",
      secondary: "button--secondary",
      tertiary: "button--tertiary",
      quiet: "button--quiet",
    },
    size: {
      sm: "button--sm",
      base: "",
      lg: "button--lg",
    },
  },
  defaultVariants: { rank: "primary", size: "base" },
});

export type ButtonRank = "primary" | "secondary" | "tertiary" | "quiet";

export interface ButtonProps {
  readonly children: ReactNode;
  readonly rank?: ButtonRank | undefined;
  readonly size?: "sm" | "base" | "lg" | undefined;
  /** `submit` only inside a form that means it: a bare button in this product does not submit. */
  readonly type?: "button" | "submit" | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly onClick?: (() => void) | undefined;
  /** Set where the label is a glyph or an icon and the button has no text of its own. */
  readonly label?: string | undefined;
  /**
   * Renders the caller's own element with the button's shape.
   *
   * The one case that needs it is navigation: `<Button asChild><Link to="/week">…</Link></Button>`.
   */
  readonly asChild?: boolean | undefined;
  readonly ref?: Ref<HTMLButtonElement> | undefined;
}

export function Button({
  children,
  rank,
  size,
  type = "button",
  isDisabled,
  onClick,
  label,
  asChild,
  ref,
}: ButtonProps) {
  const Root = asChild === true ? Slot : "button";
  return (
    <Root
      ref={ref}
      className={button({ rank, size })}
      type={asChild === true ? undefined : type}
      disabled={asChild === true ? undefined : isDisabled}
      aria-disabled={isDisabled === true ? true : undefined}
      aria-label={label}
      onClick={onClick}
    >
      {children}
    </Root>
  );
}
