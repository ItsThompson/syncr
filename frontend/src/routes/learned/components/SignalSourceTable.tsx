/* Where the learning comes from: each source, what it yields, and which parameter it drives.
 *
 * `US-LEARN-06`. The reader's question is what their own actions teach the system, and a table answers it in the
 * shape the answer has: three facts per source. Prose would bury which act drives which number.
 *
 * THE REJECTION ROW IS WHY THIS TABLE EXISTS AT ALL. Four rows about pins, partials, skips and moves read as
 * encouragement; the fifth says that rejecting a whole week yields almost nothing, with the reason, which is the
 * one thing a reader would otherwise assume the opposite of.
 *
 * IT IS STATIC AND IT CARRIES NO FIGURE. Nothing here is derived from the account's own data, so nothing here can
 * go stale against it. */

import { Panel } from "../../../ui/layout";
import { Table, type TableColumn } from "../../../ui/domain";
import { SIGNAL_SOURCES, type SignalSource } from "../signals";

const COLUMNS: readonly TableColumn<SignalSource>[] = [
  { key: "source", header: "What you do", cell: (row) => row.source },
  { key: "yields", header: "What it yields", cell: (row) => row.yields },
  { key: "drives", header: "What it drives", cell: (row) => row.drives },
];

export function SignalSourceTable() {
  return (
    <Panel title="Where the learning comes from">
      <Table
        caption="Each signal source, what it yields, and which parameter it drives"
        columns={COLUMNS}
        rows={SIGNAL_SOURCES}
        rowKey={(row) => row.source}
      />
    </Panel>
  );
}
