/* THE CONFLICT BANNER, AND THE THREE ANSWERS IT OFFERS.
 *
 * A CONFLICT IS THE ONE CONDITION IN THIS PRODUCT THAT NOTIFIES. Everything else waits to be looked at, and that
 * discipline is what makes this one land: without it a trivial improvement nags exactly like a real collision, the
 * reader mutes the lot inside a week, and then misses the collisions too. So the banner persists until the overlap is
 * answered, and the block itself carries the oxide left rule inline.
 *
 * NOTHING IS MOVED BEFORE AN ANSWER IS CHOSEN. The three answers are stated and none is taken: `move the block` marks
 * it ineligible for that window or releases its pin and re-solves, `keep both` records the answer and leaves the
 * overlap, and `retype the anchor` changes what the commitment means. syncr may never move or remove without assent,
 * and a banner is not assent.
 *
 * A MATERIALIZED TEMPLATE ENTRY OFFERS TWO PATHS AND CHOOSES NEITHER, which is `US-TPL-03`'s rule: pin this occurrence
 * elsewhere, or edit the template that produced it. The first is `moved` on this occurrence; the second is a different
 * screen, so it is a `Link` rather than a write -- a `Link` and not a raw anchor, because an anchor to a route this
 * application owns reloads the document and throws away a cache the reader is about to come back to. */

import { Link } from "react-router";

import { NoticeStrip, type Notice } from "../../../ui/domain";
import { Button } from "../../../ui/primitives";

/** One answer the reader may give, in the words the design record uses for it. */
export interface ConflictAnswer {
  readonly label: string;
  readonly onSelect: () => void;
}

export interface ConflictBannerProps {
  readonly notice: Notice;
  readonly answers: readonly ConflictAnswer[];
  /** The route the template that produced this occurrence is edited on, for a materialized entry. */
  readonly templatePath?: string | undefined;
}

export function ConflictBanner({ notice, answers, templatePath }: ConflictBannerProps) {
  return (
    <div className="flex flex-col gap-2">
      <NoticeStrip notice={notice} />
      <div className="flex flex-wrap items-center gap-2">
        {answers.map((answer) => (
          <Button key={answer.label} onClick={answer.onSelect} rank="secondary" size="sm">
            {answer.label}
          </Button>
        ))}
        {templatePath === undefined ? null : (
          <Button asChild rank="secondary" size="sm">
            <Link to={templatePath}>Edit the template</Link>
          </Button>
        )}
      </div>
    </div>
  );
}
