/* THE DETAIL PANEL. What this block is, and why it is here.
 *
 * IT OPENS ON SELECTION, NEVER ON HOVER. A reason is not a tooltip: it is a schema of labelled rows, it outlives the
 * pointer, and a reader has to be able to read it while looking at the grid. Hover is mouse-only and spends a fill
 * channel; the panel is where the words go.
 *
 * FOUR DEFINITION ROWS AND THEN THE REASON'S OWN. `when`, `source`, `type` and `authority` are facts about the block;
 * the clauses below them are what the solver computed. Both are the same form, so both are `ReasonRows`, and the label
 * column is one token wide on both.
 *
 * A PINNED BLOCK SHOWS THE THREE THINGS `US-PIN-05` NAMES: where the reader put it and when, what the solver had
 * chosen instead, and what that choice cost. The first two arrive as clauses; the cost is on the block.
 *
 * A BLOCK THE WEEK NO LONGER HOLDS RENDERS NOTHING. A solve landing can remove the selected block, and a panel that
 * kept describing it would be stating a placement that no longer exists. The screen clears the selection on the same
 * redraw, so this is the second half of one rule rather than a guard of its own. */

import { Panel } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import { ReasonRows, type LabelledRow } from "../../../ui/domain";

/** One thing that can be done to the selected block from the panel. */
export interface DetailAction {
  readonly label: string;
  readonly onSelect: () => void;
}

/* A stable empty list, so a panel with nothing to offer does not take a fresh array on every render. */
const NO_ACTIONS: readonly DetailAction[] = [];

export interface DetailPanelProps {
  readonly title: string;
  readonly definitionRows: readonly LabelledRow[];
  readonly reasonRows: readonly LabelledRow[];
  /** The objective delta a pin cost, already read, or null where the block carries none. */
  readonly cost: string | null;
  /** What can be done to this block from here: unpin, resolve, retype. Rendered in the order given. */
  readonly actions?: readonly DetailAction[] | undefined;
  readonly onClose: () => void;
}

export function DetailPanel({
  title,
  definitionRows,
  reasonRows,
  cost,
  actions = NO_ACTIONS,
  onClose,
}: DetailPanelProps) {
  return (
    <Panel
      headerEnd={
        <Button label="Close the detail panel" onClick={onClose} rank="quiet" size="sm">
          esc
        </Button>
      }
      title="Detail"
    >
      <div className="flex flex-col gap-3">
        <p className="text-base text-ink-deep">{title}</p>
        <ReasonRows label="Definition" rows={definitionRows} />
        <ReasonRows label="Reason" rows={rowsWithCost(reasonRows, cost)} />
        {actions.length === 0 ? null : (
          <div className="flex flex-wrap gap-2">
            {actions.map((action) => (
              <Button key={action.label} onClick={action.onSelect} rank="secondary" size="sm">
                {action.label}
              </Button>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

/**
 * The reason's rows, with the pin's cost as one more.
 *
 * The delta is stored on the block rather than in a clause of its own, and the design record renders it as a `cost`
 * row beside the clauses. Composing it here rather than in `reasons.ts` keeps the clause narrowing a pure mapping of
 * the six kinds: a seventh row that is not a clause would make that mapping lie about its own bound.
 */
function rowsWithCost(rows: readonly LabelledRow[], cost: string | null): LabelledRow[] {
  return cost === null ? [...rows] : [...rows, { label: "cost", value: cost }];
}
