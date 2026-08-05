/* The proposed revision: approve it whole, adjust it first, or reject it.
 *
 * SYNCR NEVER RE-CUTS THE BUDGET ON ITS OWN. Nothing here is applied until the reader approves it, and the
 * panel's footer says so in the api's own sentence rather than this screen's paraphrase of it. Rejecting is
 * therefore not a write at all: it closes the proposal, and the budget stays what the reader declared.
 *
 * ADJUSTING TAKES THE SAME ROUTE AS APPROVING. One endpoint, one body: a caller applying the proposal sends
 * the proposal's figures and a caller adjusting it sends its own, so an adjusted revision cannot take a path a
 * whole one does not. That is the api's shape and this panel is why it has it.
 *
 * BELOW A QUARTER OF CONFIRMED WEEKS THERE IS NOTHING TO PROPOSE, and the panel states how much evidence is
 * missing instead of rendering an empty table. The gap between actual and target is the deviation chart, which
 * this mode shows beside the trend, so the review still says something useful with three weeks of data.
 *
 * THE VACANCY'S ROW CARRIES NO AREA AND IS NOT SUBMITTED. It is the gap the review exists to surface, and its
 * share follows from the Areas' own rather than being a figure anything can be written to. */

import { useState } from "react";

import { AreaChip, EmptyState, Table, areaPigment, type TableColumn } from "../../../ui/domain";
import { Button, NumberStepper } from "../../../ui/primitives";
import { Panel } from "../../../ui/layout";
import { VACANCY_LABEL } from "../entries";
import { asPercent, asWholePercent } from "../figures";
import type { Area } from "../../../api/hooks/useAreas";
import type {
  BudgetProposal,
  BudgetRevisionBody,
  ProposedShare,
} from "../../../api/hooks/useBudgetReview";
import type { Write } from "../../../api/hooks/useWrite";

const SHARE_MAX = 100;

export interface ProposalPanelProps {
  readonly proposal: BudgetProposal;
  readonly areas: readonly Area[];
  readonly write: Write<BudgetRevisionBody>;
}

/** Whatever the reader adjusted a row to, by Area id. A row nobody touched is not a member. */
type Adjustments = Readonly<Record<string, number>>;

/** The figures a submit sends: every Area row, at the adjusted figure or the proposed one. */
export function bodyOf(
  shares: readonly ProposedShare[],
  adjusted: Adjustments,
): BudgetRevisionBody {
  return {
    percentages: shares.flatMap((share) =>
      share.areaId === null
        ? []
        : [
            {
              areaId: share.areaId,
              budgetPercent: adjusted[share.areaId] ?? share.proposedPercent,
            },
          ],
    ),
  };
}

/* Built outside the component, for the reason `AreaTable`'s are: a cell is a function the table calls per row
 * rather than an element it mounts, and one defined during render reads to a linter as a nested component. */
function columnsFor(
  areas: readonly Area[],
  adjusted: Adjustments,
  onAdjust: (areaId: string, percent: number) => void,
): readonly TableColumn<ProposedShare>[] {
  return [
    {
      key: "area",
      header: "Area",
      cell: (share) => {
        const found = areas.find((area) => area.id === share.areaId);
        if (found === undefined) return VACANCY_LABEL;
        return <AreaChip pigment={areaPigment(found.pigmentIndex)} name={found.name} />;
      },
    },
    {
      key: "target",
      header: "Target now",
      measure: "figure",
      cell: (share) => asWholePercent(share.declaredPercent),
    },
    {
      key: "observed",
      header: "Observed",
      measure: "figure",
      cell: (share) => asPercent(share.observedPercent),
    },
    {
      key: "proposed",
      header: "Proposed",
      measure: "figure",
      cell: (share) => {
        const areaId = share.areaId;
        if (areaId === null) return asWholePercent(share.proposedPercent);
        return (
          <NumberStepper
            value={adjusted[areaId] ?? share.proposedPercent}
            onValueChange={(next) => onAdjust(areaId, next)}
            measure="actual-minutes"
            min={0}
            max={SHARE_MAX}
            unit="%"
            label={`Proposed share for ${areaId}`}
          />
        );
      },
    },
    { key: "basis", header: "Basis", cell: (share) => share.statement },
  ];
}

export function ProposalPanel({ proposal, areas, write }: ProposalPanelProps) {
  const [adjusted, setAdjusted] = useState<Adjustments>({});
  const [isRejected, setIsRejected] = useState(false);

  if (proposal.shares.length === 0) {
    return (
      <Panel title="Proposed revision">
        <EmptyState title="Not enough confirmed data yet" detail={proposal.statement} />
      </Panel>
    );
  }

  if (isRejected) {
    return (
      <Panel title="Proposed revision">
        <EmptyState
          title="The proposal was rejected"
          detail={
            "Nothing was applied and your budget is unchanged. The review is a read, so rejecting it " +
            "writes nothing and the next one starts from the same declaration."
          }
          action={
            <Button rank="secondary" onClick={() => setIsRejected(false)}>
              Show it again
            </Button>
          }
        />
      </Panel>
    );
  }

  return (
    <Panel
      title="Proposed revision"
      headerEnd={
        <span className="text-eyebrow">derived from {proposal.confirmedWeeks} confirmed weeks</span>
      }
      footer={<span>{proposal.statement}</span>}
    >
      <Table
        columns={columnsFor(areas, adjusted, (areaId, percent) =>
          setAdjusted({ ...adjusted, [areaId]: percent }),
        )}
        rows={proposal.shares}
        rowKey={(share) => share.areaId ?? VACANCY_LABEL}
        caption="The share each category declares, what it held, and what to declare instead"
      />
      <span className="mt-2 flex items-center gap-2">
        <Button onClick={() => void write.submit(bodyOf(proposal.shares, adjusted))}>
          Approve the revision
        </Button>
        <Button rank="secondary" onClick={() => setAdjusted({})}>
          Reset the adjustments
        </Button>
        <Button rank="secondary" onClick={() => setIsRejected(true)}>
          Reject
        </Button>
      </span>
      {write.problem === null ? null : (
        <p role="alert" className="text-sm text-signal-oxide">
          {write.problem.detail}
        </p>
      )}
    </Panel>
  );
}
