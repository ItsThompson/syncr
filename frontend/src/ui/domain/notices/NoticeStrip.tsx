/* VOLUME 3: the banner, persistently in the top bar until the condition clears.
 *
 * The loudest volume in the product, and there is nothing above it: level 4, a blocking notice, is deliberately
 * unused. Two cases earn this volume, and both are silent failures a reader would otherwise never see: the write
 * target's token expiring, which quietly stops the plan reaching their phone, and a calendar reconciliation that
 * failed. An external anchor overlapping a planned block takes it too, while the conflict is unresolved.
 *
 * It is DISMISSED BY THE CONDITION CLEARING, not by a reader. `onDismiss` is offered for the cases where an
 * acknowledgement is the resolution, and a banner without one simply stays: a notice a reader can wave away is a
 * notice about something nobody fixed. */

import { useId } from "react";

import { Button } from "../../primitives";
import { NoticeBody } from "./NoticeBody";
import type { Notice } from "./notice";
import { noticeRole, noticeSurface } from "./surface";
import "./notices.css";

export interface NoticeStripProps {
  readonly notice: Notice;
  /** Renders the instant in the reader's zone. Without one, the notice states no age. */
  readonly formatSince?: ((iso: string) => string) | undefined;
  /** Offered only where acknowledging IS the resolution. */
  readonly onDismiss?: (() => void) | undefined;
}

export function NoticeStrip({ notice, formatSince, onDismiss }: NoticeStripProps) {
  const titleId = useId();

  return (
    <div
      className={noticeSurface({ volume: "banner", pigment: notice.pigment })}
      role={noticeRole(notice.pigment)}
      aria-labelledby={titleId}
    >
      <NoticeBody notice={notice} layout="line" titleId={titleId} formatSince={formatSince} />
      {notice.action === null ? null : (
        <Button asChild rank="secondary" size="sm">
          <a href={notice.action.href}>{notice.action.label}</a>
        </Button>
      )}
      {onDismiss === undefined ? null : (
        <Button rank="quiet" size="sm" label="Dismiss this notice" onClick={onDismiss}>
          <span className="glyph glyph--cross" aria-hidden="true" />
        </Button>
      )}
    </div>
  );
}
