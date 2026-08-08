/* THE PROMOTION CANDIDATES: what the reader keeps pinning, offered as a template change.
 *
 * AMBER, AT PANEL VOLUME, AND IN SESSION MODE ONLY, which is the row section 16's notice-volume table gives it: an
 * available promotion reads "needs attention, nothing is broken", exactly as a chronic skip does. The surface is
 * `noticeSurface`'s own amber panel rather than a second declaration of it, so this and every other volume-2 amber
 * notice in the product cannot come to look different.
 *
 * IT RENDERS ONLY WHEN THERE IS A CANDIDATE, because the table's row is "promotion AVAILABLE". An amber surface saying
 * nothing has been pinned three weeks running would spend a notice pigment on the absence of a notice, and the raised
 * panel beside it already states the quiet case.
 *
 * EVERY WORD AND EVERY FIGURE HERE IS THE API'S. The binding's name arrives resolved, including the fallback for content
 * the window can no longer name, because a repeated collision needs the same answer and two clients spelling one absence
 * two ways is the defect the api owns these words to prevent. This file composes only what the wire cannot: the weekday,
 * which is a label for an ISO number.
 *
 * NOTHING IS APPLIED WITHOUT AN ACCEPT, and the api's own closing line says so. Accepting moves the day-shape entry the
 * pattern names; declining writes nothing to any template and stops the question being asked for a stated interval.
 *
 * THE ACCEPT CONTROL IS DRAWN ONLY FOR A PATTERN THE TEMPLATE CAN ABSORB. A promotion MOVES an entry, so content no
 * entry holds has nothing to move: the api sends the reason on the candidate, this panel renders it in place of the
 * control, and a reader is told the limit where they meet it rather than by pressing a button that refuses. The
 * DECLINE is offered either way, because the answer it records is about the asking rather than about the template. */

import { Button } from "../../../../ui/primitives";
import { Table, type TableColumn } from "../../../../ui/domain";
import { noticeRole, noticeSurface } from "../../../../ui/domain/notices/surface";
import type { PromotionCandidate } from "../../../../api/hooks/useWeeklySession";
import type { PromotionBody } from "../../../../api/hooks/usePromotions";
import type { Write } from "../../../../api/hooks/useWrite";
import "../../../../ui/domain/notices/notices.css";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export interface PromotionPanelProps {
  readonly candidates: readonly PromotionCandidate[];
  /** The api's own sentence that nothing is applied without acceptance. */
  readonly statement: string;
  readonly accept: Write<PromotionBody>;
  readonly decline: Write<PromotionBody>;
}

export function PromotionPanel({ candidates, statement, accept, decline }: PromotionPanelProps) {
  if (candidates.length === 0) return null;

  const refused = accept.problem ?? decline.problem;

  return (
    <section
      aria-label="Repeated pins"
      className={noticeSurface({ volume: "panel", pigment: "amber" })}
      role={noticeRole("amber")}
    >
      <div className="notice__content">
        <b className="notice__title">Repeated pins</b>
        <Table
          caption="Content pinned to one time for three or more consecutive weeks"
          columns={columns(accept, decline)}
          rowKey={(row) => row.id}
          rows={candidates.map((candidate) => ({
            id: candidate.id,
            binding: candidate.title,
            time: `${weekdayOf(candidate.weekday)} ${candidate.localTime}`,
            weeks: `${String(candidate.consecutiveWeeks)} weeks`,
            acceptRefusal: candidate.acceptRefusal,
          }))}
        />
        <p className="notice__detail">{statement}</p>
        {refused === null ? null : <p className="notice__detail">{refused.detail}</p>}
      </div>
    </section>
  );
}

interface PromotionRow {
  readonly id: string;
  readonly binding: string;
  readonly time: string;
  readonly weeks: string;
  /** Why the template cannot absorb this one, or null when it can. */
  readonly acceptRefusal: string | null;
}

/** The two answers, or the reason there is only one of them. */
function AnswerCell({
  row,
  accept,
  decline,
}: {
  readonly row: PromotionRow;
  readonly accept: Write<PromotionBody>;
  readonly decline: Write<PromotionBody>;
}) {
  return (
    <div className="flex flex-col items-start gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {row.acceptRefusal === null ? (
          <Button
            rank="secondary"
            size="sm"
            onClick={() => void accept.submit({ promotionId: row.id })}
          >
            Accept
          </Button>
        ) : null}
        <Button rank="quiet" size="sm" onClick={() => void decline.submit({ promotionId: row.id })}>
          Decline
        </Button>
      </div>
      {row.acceptRefusal === null ? null : (
        <span className="text-sm text-text-muted">{row.acceptRefusal}</span>
      )}
    </div>
  );
}

function columns(
  accept: Write<PromotionBody>,
  decline: Write<PromotionBody>,
): readonly TableColumn<PromotionRow>[] {
  return [
    { key: "binding", header: "Binding", cell: (row) => row.binding },
    { key: "time", header: "Time", cell: (row) => row.time },
    { key: "weeks", header: "Weeks", measure: "figure", cell: (row) => row.weeks },
    {
      key: "answer",
      header: "Your answer",
      cell: (row) => <AnswerCell row={row} accept={accept} decline={decline} />,
    },
  ];
}

/** The ISO weekday as a template entry names it. Monday is 1, which is what `isoweekday` answers. */
function weekdayOf(weekday: number): string {
  return WEEKDAYS[weekday - 1] ?? "";
}
