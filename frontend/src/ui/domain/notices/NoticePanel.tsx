/* VOLUME 2: the panel, at the head of the affected screen.
 *
 * The volume the week's own infeasibility takes: a reader walks past it to reach the screen's content, and it
 * names the shortfall, what is unavailable and what still works, each on a row of its own.
 *
 * The action is a real link with an href, never a button that assigns a location, because a notice's repair is
 * as often an external re-authorisation as it is a screen in this product. */

import { useId } from "react";

import { Button } from "../../primitives";
import { NoticeBody } from "./NoticeBody";
import type { Notice } from "./notice";
import { noticeRole, noticeSurface } from "./surface";
import "./notices.css";

export interface NoticePanelProps {
  readonly notice: Notice;
  /** Renders the instant in the reader's zone. Without one, the notice states no age. */
  readonly formatSince?: ((iso: string) => string) | undefined;
}

export function NoticePanel({ notice, formatSince }: NoticePanelProps) {
  const titleId = useId();

  return (
    <section
      className={noticeSurface({ volume: "panel", pigment: notice.pigment })}
      role={noticeRole(notice.pigment)}
      aria-labelledby={titleId}
    >
      <NoticeBody notice={notice} layout="rows" titleId={titleId} formatSince={formatSince} />
      {notice.action === null ? null : (
        <Button asChild rank="secondary">
          <a href={notice.action.href}>{notice.action.label}</a>
        </Button>
      )}
    </section>
  );
}
