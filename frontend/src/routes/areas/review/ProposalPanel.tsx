/* The proposed revision: approve it whole, adjust it first, or reject it.
 *
 * SYNCR NEVER RE-CUTS THE BUDGET ON ITS OWN. Nothing here is applied until the reader approves it, and the
 * panel's footer says so in the api's own sentence rather than this screen's paraphrase of it. Rejecting is
 * therefore not a write at all: it closes the proposal, and the budget stays what the reader declared.
 *
 * ADJUSTING TAKES THE SAME ROUTE AS APPROVING. One endpoint, one body: a caller applying the proposal sends
 * the proposal's figures and a caller adjusting it sends its own, so an adjusted revision cannot take a path a
 * whole one does not.
 *
 * THE ADJUST FIELD IS A PLAIN FIGURE AND NOT A STEPPER, and the reason is durable rather than historical: a share
 * is stored as `NUMERIC(5, 2)` and the api bounds it by range alone, so the field has no grid for a step to land
 * on. `NumberStepper` snaps every commit to its measure's step, so no measure of it is right here, not even one
 * stepping by 1. The api's bounds refuse a figure out of range and its 422 names the field, which this panel
 * renders.
 *
 * TEXT THAT IS NOT A FIGURE IS REFUSED rather than read as "leave this row alone". Silently applying the proposal
 * for a row the reader typed `3,5` into is the same class of defect as rounding it: what is written is not what
 * was typed, and nothing says so.
 *
 * BELOW A QUARTER OF CONFIRMED WEEKS THERE IS NOTHING TO PROPOSE, and the panel states how much evidence is
 * missing instead of rendering an empty table. The gap between actual and target is the deviation chart, which
 * this mode shows beside the trend, so the review still says something useful with three weeks of data.
 *
 * THE VACANCY'S ROW CARRIES NO AREA AND IS NOT SUBMITTED. It is the gap the review exists to surface, and its
 * share follows from the Areas' own rather than being a figure anything can be written to. */

import { useState } from "react";

import { AreaChip, EmptyState, Table, areaPigment, type TableColumn } from "../../../ui/domain";
import { Button, Input } from "../../../ui/primitives";
import { Panel } from "../../../ui/layout";
import { VACANCY_LABEL } from "../entries";
import { asPercent, asWholePercent, figureOf, figureRefusal, readFigure } from "../figures";
import type { Area } from "../../../api/hooks/useAreas";
import type {
  BudgetProposal,
  BudgetRevisionBody,
  ProposedShare,
} from "../../../api/hooks/useBudgetReview";
import type { Write } from "../../../api/hooks/useWrite";

export interface ProposalPanelProps {
  readonly proposal: BudgetProposal;
  readonly areas: readonly Area[];
  readonly write: Write<BudgetRevisionBody>;
}

/**
 * What the reader typed into a row, by Area id, as TEXT.
 *
 * Text rather than a number, so a figure mid-typing is the reader's until they submit: `3.` is not a number and
 * `33.50` is not `33.5`, and storing either as a number would rewrite the field under the caret.
 */
type Adjustments = Readonly<Record<string, string>>;

/* What a row whose Area the list no longer holds is called. The Area column answers the same case with these
 * words too, so the two cells agree rather than one of them announcing an identifier. */
const UNDECLARED_AREA = "an Area no longer declared";

/** The figures a submit sends: every Area row, at the adjusted figure or the proposed one. */
export function bodyOf(
  shares: readonly ProposedShare[],
  adjusted: Adjustments,
): BudgetRevisionBody {
  return {
    percentages: shares.flatMap((share) => {
      if (share.areaId === null) return [];
      const typed = adjusted[share.areaId];
      const figure = typed === undefined ? null : figureOf(readFigure(typed));
      return [{ areaId: share.areaId, budgetPercent: figure ?? share.proposedPercent }];
    }),
  };
}

/** Why no revision can be applied, in the reader's words, or null when one can. */
export function adjustmentRefusal(
  shares: readonly ProposedShare[],
  adjusted: Adjustments,
  areaById: ReadonlyMap<string, Area>,
): string | null {
  for (const share of shares) {
    if (share.areaId === null) continue;
    const typed = adjusted[share.areaId];
    if (typed === undefined) continue;
    const named = areaById.get(share.areaId)?.name ?? UNDECLARED_AREA;
    const refused = figureRefusal(typed, `The proposed share for ${named}`);
    if (refused !== null) return refused;
  }
  return null;
}

/* Built outside the component, for the reason `AreaTable`'s are: a cell is a function the table calls per row
 * rather than an element it mounts, and one defined during render reads to a linter as a nested component. */
function columnsFor(
  areaById: ReadonlyMap<string, Area>,
  adjusted: Adjustments,
  onAdjust: (areaId: string, text: string) => void,
): readonly TableColumn<ProposedShare>[] {
  return [
    {
      key: "area",
      header: "Area",
      cell: (share) => {
        if (share.areaId === null) return VACANCY_LABEL;
        const found = areaById.get(share.areaId);
        if (found === undefined) return UNDECLARED_AREA;
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
        /* Named by the AREA and never by its identifier: this is the one control the review mode exists to
         * offer, and a reader hearing a UUID learns nothing about which share they are changing. An Area the
         * list no longer holds takes the same words its own cell takes, two columns left. */
        const named = areaById.get(areaId)?.name ?? UNDECLARED_AREA;
        const typed = adjusted[areaId];
        return (
          <Input
            measure="figure"
            value={typed ?? String(share.proposedPercent)}
            onValueChange={(text) => onAdjust(areaId, text)}
            isInvalid={typed !== undefined && readFigure(typed).kind === "unreadable"}
            label={`Proposed share for ${named}, as a percentage`}
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
  const areaById = new Map(areas.map((area) => [area.id, area]));
  const unreadable = adjustmentRefusal(proposal.shares, adjusted, areaById);

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
        columns={columnsFor(areaById, adjusted, (areaId, text) =>
          setAdjusted({ ...adjusted, [areaId]: text }),
        )}
        rows={proposal.shares}
        rowKey={(share) => share.areaId ?? VACANCY_LABEL}
        caption="The share each category declares, what it held, and what to declare instead"
      />
      <span className="mt-2 flex items-center gap-2">
        <Button
          isDisabled={unreadable !== null}
          onClick={() => void write.submit(bodyOf(proposal.shares, adjusted))}
        >
          Approve the revision
        </Button>
        <Button rank="secondary" onClick={() => setAdjusted({})}>
          Reset the adjustments
        </Button>
        <Button rank="secondary" onClick={() => setIsRejected(true)}>
          Reject
        </Button>
      </span>
      {unreadable === null ? null : (
        <p role="alert" className="text-sm text-signal-oxide">
          {unreadable}
        </p>
      )}
      {write.problem === null ? null : (
        <p role="alert" className="text-sm text-signal-oxide">
          {write.problem.detail}
        </p>
      )}
    </Panel>
  );
}
