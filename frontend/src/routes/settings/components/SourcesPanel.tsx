/* The anchor sources, as the table US-CAL-05 requires: provider, anchor count, last sync, and state.
 *
 * A COUNT THAT CHANGES IS HOW SYNC PROGRESS IS REPORTED. There is no spinner and no progress bar here, and there
 * is none in the kit to reach for: pressing `Sync` re-reads the source, the anchor count in its row changes, and
 * that discrete redraw is the whole report. That is US-ERR-05's rule and US-CAL-05 states it again for this table.
 *
 * `excluded` IS NOT AN ERROR AND THE STATE COLUMN SAYS SO. A reader asked for zero anchors from that source, so
 * reporting it in the same words as a feed that could not be read would be telling them something broke when
 * they turned it off themselves. The api's own four states are rendered as they arrive.
 *
 * THE STALENESS PANEL IS NOT HERE. A source that has been failing longer than the threshold raises a panel at the
 * head of the screen, which is volume 2, because it is about the plan rather than about the row. What the row
 * carries is the state word and the instant, which is what makes the panel's claim checkable. */

import { Table, type TableColumn } from "../../../ui/domain";
import { Panel } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import { statedInstant } from "../format";
import { Refusal } from "./Refusal";
import type {
  CalendarSource,
  SourceInclusion,
  SourceReference,
} from "../../../api/hooks/useCalendarSources";
import type { Write } from "../../../api/hooks/useWrite";

export interface SourcesPanelProps {
  readonly sources: readonly CalendarSource[];
  /** The zone every instant in the table is rendered in, and the only zone shown. */
  readonly zone: string;
  readonly inclusion: Write<SourceInclusion>;
  readonly removal: Write<SourceReference>;
  readonly sync: Write<SourceReference>;
}

/* Built outside the component: a cell is a function the table CALLS per row rather than an element it mounts, so
 * it is not a component, and defining one inside a component reads to a linter as a nested component whose subtree
 * would remount. */
function columnsFor({
  zone,
  inclusion,
  removal,
  sync,
}: Omit<SourcesPanelProps, "sources">): readonly TableColumn<CalendarSource>[] {
  return [
    { key: "name", header: "Source", cell: (source) => source.displayName },
    { key: "provider", header: "Provider", cell: (source) => source.provider },
    {
      key: "anchors",
      header: "Anchors",
      measure: "figure",
      cell: (source) => source.anchorCount,
    },
    {
      key: "last-sync",
      header: "Last sync",
      cell: (source) => statedInstant(source.syncState.lastSuccessAt, zone),
    },
    { key: "state", header: "State", cell: (source) => source.state },
    { key: "role", header: "Role", cell: (source) => source.role },
    {
      key: "acts",
      header: "",
      cell: (source) => (
        <span className="flex flex-wrap gap-2">
          <Button rank="quiet" size="sm" onClick={() => void sync.submit({ sourceId: source.id })}>
            Sync
          </Button>
          <Button
            rank="quiet"
            size="sm"
            onClick={() =>
              void inclusion.submit({ sourceId: source.id, included: !source.included })
            }
          >
            {source.included ? "Exclude" : "Include"}
          </Button>
          <Button
            rank="quiet"
            size="sm"
            onClick={() => void removal.submit({ sourceId: source.id })}
          >
            Remove
          </Button>
        </span>
      ),
    },
  ];
}

export function SourcesPanel({ sources, zone, inclusion, removal, sync }: SourcesPanelProps) {
  const refusal = inclusion.problem ?? removal.problem ?? sync.problem;

  return (
    <Panel title="Anchor sources" headerEnd={<span>{sources.length}</span>}>
      <p className="text-sm text-text-muted">
        A count that changes is how a sync reports progress. Nothing here spins.
      </p>
      <Table
        columns={columnsFor({ zone, inclusion, removal, sync })}
        rows={sources}
        rowKey={(source) => source.id}
        caption="Anchor sources, with provider, anchor count, last sync and state"
        countLabel={(count) => `${count} source${count === 1 ? "" : "s"}`}
      />
      <Refusal problem={refusal} />
    </Panel>
  );
}
