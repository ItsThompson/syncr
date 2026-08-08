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
 * IT IS RAISED, NEVER APPLIED. `US-TPL-05` says nothing reaches the template without the reader accepting, and the
 * closing line says so in the api's own words.
 *
 * NO ACCEPT AND NO DECLINE HERE. Both are routes of their own and belong to the Learned screen's ticket, which also
 * owns the interval a decline suppresses a candidate for. Rendering a control this build cannot honour would be worse
 * than rendering the question: a reader who pressed it would be told nothing happened.
 *
 * THE NUMBERS ARE THE CANDIDATE'S OWN. The count of weeks comes from the run the detection found rather than from the
 * threshold it passed, so a five-week pattern says five. */

import { Table, type TableColumn } from "../../../../ui/domain";
import { noticeRole, noticeSurface } from "../../../../ui/domain/notices/surface";
import type { PromotionCandidate } from "../../../../api/hooks/useWeeklySession";
import "../../../../ui/domain/notices/notices.css";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export interface PromotionPanelProps {
  readonly candidates: readonly PromotionCandidate[];
  /** The api's own sentence that nothing is applied without acceptance. */
  readonly statement: string;
  /** Each content's name by the id the candidate carries, so a row names the thing rather than a digest. */
  readonly titles: ReadonlyMap<string, string>;
}

export function PromotionPanel({ candidates, statement, titles }: PromotionPanelProps) {
  if (candidates.length === 0) return null;

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
          columns={COLUMNS}
          rowKey={(row) => row.id}
          rows={candidates.map((candidate) => ({
            id: `${candidate.entityId}:${candidate.localTime}:${String(candidate.weekday)}`,
            binding: titles.get(candidate.entityId) ?? candidate.kind,
            time: `${weekdayOf(candidate.weekday)} ${candidate.localTime}`,
            weeks: `${String(candidate.consecutiveWeeks)} weeks`,
          }))}
        />
        <p className="notice__detail">{statement}</p>
      </div>
    </section>
  );
}

interface PromotionRow {
  readonly id: string;
  readonly binding: string;
  readonly time: string;
  readonly weeks: string;
}

const COLUMNS: readonly TableColumn<PromotionRow>[] = [
  { key: "binding", header: "Binding", cell: (row) => row.binding },
  { key: "time", header: "Time", cell: (row) => row.time },
  { key: "weeks", header: "Weeks", measure: "figure", cell: (row) => row.weeks },
];

/** The ISO weekday as a template entry names it. Monday is 1, which is what `isoweekday` answers. */
function weekdayOf(weekday: number): string {
  return WEEKDAYS[weekday - 1] ?? "";
}
