/* The notice's own content, shared by all three volumes: the mark, the title, the detail, and what still works.
 *
 * IT IS ONE FILE BECAUSE THE THREE VOLUMES MUST NOT DIVERGE. Volume is position: the same notice reads the same
 * whether it sits inline at the row it concerns, at the head of the screen, or in the top bar, and three copies
 * of this markup is how one of them comes to drop the surviving-capability line that the type exists to force.
 *
 * WHAT STILL WORKS IS RENDERED AT EVERY VOLUME. The panel gives each capability a row of its own; the two
 * one-line volumes join them, because a list in the top bar would push the plan down the page.
 *
 * `since` IS FORMATTED BY THE CALLER OR NOT AT ALL. How an instant reads depends on the reader's home zone or
 * their travel override, which the domain knows and a kit component does not, so the formatter arrives as a
 * function and the line is absent without one. That is the same rule that makes today a prop on the calendar. */

import type { Notice } from "./notice";
import { NoticeMark } from "./NoticeMark";

const NOTHING_SURVIVES = "nothing is available while the whole product is down";

/* Both readers below branch on `isWholeProductDown`, which is the field the type introduced and the one a reader
 * searching for the total-outage case will find. The array's length says the same thing under the type, and says it
 * in a way nothing points at. */

/** One row per capability, which is the panel volume's form. */
function capabilityRows(notice: Notice): string[] {
  const unavailable = notice.unavailable.map((capability) => `unavailable · ${capability}`);
  if (notice.isWholeProductDown === true) return [...unavailable, NOTHING_SURVIVES];
  return [...unavailable, ...notice.stillWorks.map((works) => `still works · ${works}`)];
}

/** The same fact in one line, which is what the two one-line volumes have room for. */
function capabilityLine(notice: Notice): string {
  if (notice.isWholeProductDown === true) return NOTHING_SURVIVES;
  return `still works · ${notice.stillWorks.join(", ")}`;
}

export interface NoticeBodyProps {
  readonly notice: Notice;
  /** `rows` for the panel volume, `line` for the two that are one line tall. */
  readonly layout: "rows" | "line";
  /** The id the volume's own container is labelled by. */
  readonly titleId: string;
  /** Renders the instant in the reader's zone. Without one, the notice states no age. */
  readonly formatSince?: ((iso: string) => string) | undefined;
}

export function NoticeBody({ notice, layout, titleId, formatSince }: NoticeBodyProps) {
  const since =
    notice.since === null || formatSince === undefined ? null : formatSince(notice.since);
  const capabilities = layout === "rows" ? capabilityRows(notice) : [capabilityLine(notice)];

  return (
    <>
      <NoticeMark pigment={notice.pigment} />
      <div className="notice__content">
        <b className="notice__title" id={titleId}>
          {notice.title}
        </b>
        <p className="notice__detail">{notice.detail}</p>
        <div className="notice__capabilities">
          {capabilities.map((capability) => (
            <span key={capability} className="notice__capability">
              {capability}
            </span>
          ))}
        </div>
        {since === null ? null : <p className="notice__since">since {since}</p>}
      </div>
    </>
  );
}
