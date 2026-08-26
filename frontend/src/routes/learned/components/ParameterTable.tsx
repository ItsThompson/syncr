/* The per-parameter table: the value, the evidence behind it, the meter, and what it means.
 *
 * THE METER IS BOUNDED AND DRAWN IN BLOCK CHARACTERS, because unlock progress runs 0 to 100% and has a known
 * end. `DataBar` is the unbounded form and is deliberately a different shape; the two are not to be unified,
 * and each states its half of that reasoning in the kit.
 *
 * EVERY ROW CARRIES ITS SENTENCE, AND THE SENTENCE IS THE API'S. `You estimate 60m for Fitness; your actual
 * median is 82m` is what builds trust, more than the figure beside it, and it is composed server-side so the
 * screen cannot describe a parameter one way while the CLI describes it another. It sits under the name rather
 * than in a column of its own: a prose column would be wider than the six figures put together.
 *
 * `shrinkage_weight` IS A COLUMN, so "still collecting" is a visible QUANTITY rather than a badge. A row at 91%
 * prior and a row at 9% prior are both "collecting", and only the figure tells them apart.
 *
 * THE STATE CELL SPENDS NO SIGNAL PIGMENT. Collecting renders at informational volume, in the table's own ink,
 * because nothing is broken while a parameter collects: marking it in oxide would teach the reader to distrust
 * a working system, and marking it in amber would ask them to attend to something they cannot act on. */

import { MaturityMeter, Table, type TableColumn } from "../../../ui/domain";
import { asShare, asValue, progressLabel, rowLabel } from "../figures";
import type { LearnedParameter } from "../../../api/hooks/useLearned";

/** The state the api sends for a parameter below its gate, which is the one the footer counts. */
const COLLECTING = "collecting";

export interface ParameterTableProps {
  readonly parameters: readonly LearnedParameter[];
}

/** The state, in the one word the api sends, at informational volume and with no mark. */
function StateCell({ state }: { readonly state: string }) {
  return <span className="text-eyebrow tracking-eyebrow uppercase text-text-muted">{state}</span>;
}

/** The name, with what it is about and the sentence that says what the figure means underneath it. */
function ParameterCell({ row }: { readonly row: LearnedParameter }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-ink">{rowLabel(row.parameter, row.subject)}</span>
      <span className="text-sm text-ink-soft">{row.plainLanguage}</span>
    </div>
  );
}

const COLUMNS: readonly TableColumn<LearnedParameter>[] = [
  { key: "parameter", header: "Parameter", cell: (row) => <ParameterCell row={row} /> },
  { key: "value", header: "Value", measure: "figure", cell: (row) => asValue(row.value) },
  { key: "samples", header: "Samples", measure: "figure", cell: (row) => String(row.samples) },
  { key: "needed", header: "Needed", measure: "figure", cell: (row) => String(row.threshold) },
  {
    key: "progress",
    header: "Progress",
    cell: (row) => (
      <MaturityMeter
        value={row.samples}
        bound={row.threshold}
        label={progressLabel(row.parameter, row.subject)}
      />
    ),
  },
  {
    key: "prior",
    header: "Still prior",
    measure: "figure",
    cell: (row) => asShare(row.shrinkageWeight),
  },
  { key: "state", header: "State", cell: (row) => <StateCell state={row.state} /> },
];

/** The footer's sentence: how many rows, and how many of them are still gathering evidence.
 *
 * Counted from `state`, which is the field the row beside it renders and the one the gate is expressed in. The
 * band states the api's own `collecting`, and the kit's table sums its footer from the rows it drew, so both
 * figures read the same fact rather than two: an earlier version counted a null value instead, which agrees with
 * the state today only because the api refuses a row where the two disagree. */
function countLabel(parameters: readonly LearnedParameter[]): (count: number) => string {
  return (count) => {
    const collecting = parameters.filter((row) => row.state === COLLECTING).length;
    return `${count} ${count === 1 ? "parameter" : "parameters"} \u00b7 ${collecting} still collecting`;
  };
}

export function ParameterTable({ parameters }: ParameterTableProps) {
  return (
    <Table
      caption="Every parameter syncr fits, its value, the evidence behind it and its state"
      columns={COLUMNS}
      rows={parameters}
      rowKey={(row) => row.parameter}
      countLabel={countLabel(parameters)}
    />
  );
}
