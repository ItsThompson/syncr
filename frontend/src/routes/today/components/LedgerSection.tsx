/* One of the day's two runs of rows, under the heading that says what the run is.
 *
 * TWO SECTIONS, ALWAYS, and each says so when it holds nothing. A day with everything behind it and a day
 * not yet started are both ordinary, and a section that disappeared would make the reader work out which of
 * the two they are looking at from the rows that remain.
 *
 * THE BORDERED BOX IS THE LAYOUT LAYER'S PANEL. A row draws itself and its hairline, and a second definition
 * of a bordered block on raised paper would be the same two declarations under another name. */

import { Panel } from "../../../ui/layout";
import type { Notice } from "../../../ui/domain";
import type { DayRow } from "../../../api/hooks/useDay";
import { OutcomeRow } from "./OutcomeRow";
import type { LedgerSectionKind, OutcomeForm, RowActions } from "../types";
import type { AreaPigment } from "../../../ui/domain";

export interface LedgerSectionProps {
  readonly title: string;
  readonly section: LedgerSectionKind;
  readonly rows: readonly DayRow[];
  readonly zone: string;
  /** The ramp step each Area holds, so a chip is never drawn without its assigned pigment. */
  readonly pigments: ReadonlyMap<string, AreaPigment>;
  /** What this run states when it holds no row. */
  readonly emptyStatement: string;
  /** The form open anywhere on the day, which at most one of these rows holds. */
  readonly form: OutcomeForm | null;
  /** The last refused recording, which at most one of these rows holds. */
  readonly refusal: { readonly blockId: string; readonly notice: Notice } | null;
  /** The row the route's cursor marks, if it belongs to this section. */
  readonly currentBlockId: string | null;
  readonly actions: RowActions;
  /** A count, a provenance line, or the keys this run answers to. */
  readonly footer?: string | undefined;
}

/** The chip and the name, or the name alone when the ramp holds no step for it; nothing only where the block
 * carries no Area at all. */
function areaOf(
  row: DayRow,
  pigments: ReadonlyMap<string, AreaPigment>,
): { readonly name: string; readonly pigment?: AreaPigment } | undefined {
  if (row.areaId === null || row.areaName === null) return undefined;
  const pigment = pigments.get(row.areaId);
  return pigment === undefined ? { name: row.areaName } : { name: row.areaName, pigment };
}

export function LedgerSection({
  title,
  section,
  rows,
  zone,
  pigments,
  emptyStatement,
  form,
  refusal,
  currentBlockId,
  actions,
  footer,
}: LedgerSectionProps) {
  return (
    <Panel title={title} footer={footer}>
      {rows.length === 0 ? (
        <p className="p-2.75 text-sm text-ink-soft">{emptyStatement}</p>
      ) : (
        rows.map((row) => (
          <OutcomeRow
            key={row.blockId}
            row={row}
            zone={zone}
            section={section}
            area={areaOf(row, pigments)}
            form={form?.blockId === row.blockId ? form : null}
            refusal={refusal?.blockId === row.blockId ? refusal.notice : null}
            isCurrent={currentBlockId === row.blockId}
            actions={actions}
          />
        ))
      )}
    </Panel>
  );
}
