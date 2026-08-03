/* The shape all three nothing-to-show surfaces share: a mark, a title, a sentence, and whatever the reader can
 * do about it.
 *
 * ONE FILE, because the three answer one question in three ways and a reader should not have to learn three
 * layouts to read "there is nothing here yet", "it is coming" and "it did not arrive". What differs between them
 * is the pigment of the mark, whether a screen reader is told, and whether there is anything to do.
 *
 * NOTHING HERE SPINS, AND THERE IS NOTHING IT COULD SPIN WITH: the kit has no spinner, no skeleton and no
 * progress bar, `--duration` is zero, and the theme clears every animation namespace. A pending surface says what
 * it is waiting for in words instead, which is more than a spinner has ever said. */

import type { ReactNode } from "react";
import { cva } from "class-variance-authority";

import "../../primitives/glyphs.css";
import "./status.css";

const surface = cva("status", {
  variants: {
    kind: {
      empty: "",
      pending: "",
      error: "status--error",
    },
  },
});

const mark = cva("glyph status__mark", {
  variants: {
    kind: {
      empty: "glyph--notice-info",
      pending: "glyph--notice-info",
      error: "glyph--cross",
    },
  },
});

/* A pending surface is announced politely and a failure interrupts; an empty one is neither, because it is the
 * screen's own content rather than something that happened. */
const ROLE = {
  empty: undefined,
  pending: "status",
  error: "alert",
} as const;

export type StatusKind = "empty" | "pending" | "error";

export interface StatusSurfaceProps {
  readonly kind: StatusKind;
  /** One line, in the reader's words: what is not here, or what is being waited for. */
  readonly title: string;
  /** Why, and what it means for the plan. */
  readonly detail: string;
  /** The repair, as the caller's own control: a link to a setup step, or a button that solves the week. */
  readonly action?: ReactNode;
  /** An illustration plate. Never behind data, which is why it is a sibling of the words rather than a fill. */
  readonly plate?: ReactNode;
}

export function StatusSurface({ kind, title, detail, action, plate }: StatusSurfaceProps) {
  return (
    <div className={surface({ kind })} role={ROLE[kind]}>
      {plate}
      <span className={mark({ kind })} aria-hidden="true" />
      <p className="status__title">{title}</p>
      <p className="status__detail">{detail}</p>
      {action}
    </div>
  );
}
