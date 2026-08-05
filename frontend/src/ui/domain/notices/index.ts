/* THE THREE NOTICE VOLUMES, AND THE FOURTH THAT DOES NOT EXIST.
 *
 * Volume is POSITION, not pigment: how loudly a reader should care is said by where the notice sits, and what
 * kind of thing happened is said by its pigment and its mark.
 *
 *   NoticeCard   volume 1, inline at the block or row it concerns
 *   NoticePanel  volume 2, at the head of the affected screen
 *   NoticeStrip  volume 3, persistently in the top bar until the condition clears
 *
 * LEVEL 4 IS DELIBERATELY UNUSED and this is the record of it. There is no blocking notice, no modal that a
 * reader has to answer, and no `NoticeDialog` in this barrel. syncr does not stop anyone approving a knowingly
 * broken week: infeasibility is the product's most valuable output, and a week that cannot hold its commitments
 * is impossible rather than broken. A blocking volume would also make the severity model four wide, where the
 * three volumes are already ordered by position, and `docs/design/components.html` draws the fourth once,
 * annotated, and never ships it.
 *
 * A toast is absent for the same reason: a floating transient would be a volume with no position at all. */

export { NoticeCard, type NoticeCardProps } from "./NoticeCard";
export { NoticeMark, type NoticeMarkProps } from "./NoticeMark";
export { NoticePanel, type NoticePanelProps } from "./NoticePanel";
export { NoticeStrip, type NoticeStripProps } from "./NoticeStrip";
export type { Notice, NoticeAction, NoticePigment, NoticeScope, NoticeVolume } from "./notice";
export { noticeFrom, noticesAt, outageFrom, type WireNotice } from "./notice";
