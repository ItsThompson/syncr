/* VOLUME 1: inline, at the block or the row it concerns.
 *
 * The quietest volume, and the one with no box at all: a mark, a kind, and a sentence beside the thing they
 * qualify. It is where a conflict on a block, an unconfirmed day and a parameter still collecting its baseline
 * all land, because each of those is about ONE row and a notice about one row does not belong at the head of the
 * screen.
 *
 * It carries no action. An inline notice sits on the thing it is about, so the repair is the row itself: the
 * block a reader drags, the day they confirm. An action here would be a second control competing with the row's
 * own. */

import { useId } from "react";

import { NoticeBody } from "./NoticeBody";
import type { Notice } from "./notice";
import { noticeRole, noticeSurface } from "./surface";
import "./notices.css";

export interface NoticeCardProps {
  readonly notice: Notice;
  /** Renders the instant in the reader's zone. Without one, the notice states no age. */
  readonly formatSince?: ((iso: string) => string) | undefined;
}

export function NoticeCard({ notice, formatSince }: NoticeCardProps) {
  const titleId = useId();

  return (
    <div
      className={noticeSurface({ volume: "inline", pigment: notice.pigment })}
      role={noticeRole(notice.pigment)}
      aria-labelledby={titleId}
    >
      <NoticeBody notice={notice} layout="line" titleId={titleId} formatSince={formatSince} />
    </div>
  );
}
