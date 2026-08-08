/* THE PROMOTION CANDIDATES: what the reader keeps pinning, offered as a template change.
 *
 * IT IS RAISED, NEVER APPLIED. `US-TPL-05` says nothing reaches the template without the reader accepting, and the
 * panel's footer says so in the api's own words: the promise holds whether or not there are candidates today, which is
 * why the sentence is rendered either way rather than beside a row.
 *
 * NO ACCEPT AND NO DECLINE HERE. Both are routes of their own and belong to the Learned screen's ticket, which also
 * owns the interval a decline suppresses a candidate for. Rendering a control this build cannot honour would be worse
 * than rendering the question: a reader who pressed it would be told nothing happened.
 *
 * THE NUMBERS ARE THE CANDIDATE'S OWN. The count of weeks comes from the run the detection found rather than from the
 * threshold it passed, so a five-week pattern says five. */

import { Table, type TableColumn } from "../../../../ui/domain";
import { Panel } from "../../../../ui/layout";
import type { PromotionCandidate } from "../../../../api/hooks/useWeeklySession";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export interface PromotionPanelProps {
  readonly candidates: readonly PromotionCandidate[];
  /** The api's own sentence that nothing is applied without acceptance. */
  readonly statement: string;
  /** Each content's name by the id the candidate carries, so a row names the thing rather than a digest. */
  readonly titles: ReadonlyMap<string, string>;
}

export function PromotionPanel({ candidates, statement, titles }: PromotionPanelProps) {
  return (
    <Panel
      title="Repeated pins"
      headerEnd={<span className="text-eyebrow">{candidates.length} offered</span>}
      footer={<span>{statement}</span>}
    >
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
    </Panel>
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
