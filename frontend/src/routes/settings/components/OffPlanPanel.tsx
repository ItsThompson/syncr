/* The declared off-plan periods, and the one field on each that is still a choice afterwards.
 *
 * `keepFrame` IS EDITABLE HERE, which US-OFF-02 requires: it is presented at declaration and changed afterwards.
 * The row's checkbox patches the period rather than redeclaring it, so shortening a holiday and changing what
 * survives inside it are two separate acts on one row.
 *
 * BOTH ENDS RENDER IN THE ACTIVE ZONE. A period is stored as two instants and read in one zone, which is the same
 * rule every other time on this screen follows.
 *
 * AN OVERLAP IS THE API'S 409, rendered as it arrives. Two periods that abut exactly are accepted: a period ending
 * at 09:00 leaves 09:00 itself on plan, so another may begin there. */

import { Table, type TableColumn } from "../../../ui/domain";
import { Panel } from "../../../ui/layout";
import { Button, Checkbox } from "../../../ui/primitives";
import { statedInstant } from "../format";
import { KEEP_FRAME_MEANINGS } from "../offPlan";
import { OffPlanDeclaration } from "./OffPlanDeclaration";
import { Refusal } from "./Refusal";
import type {
  OffPlanCreateBody,
  OffPlanEdit,
  OffPlanPeriod,
  OffPlanRemoval,
} from "../../../api/hooks/useOffPlan";
import type { Write } from "../../../api/hooks/useWrite";

export interface OffPlanPanelProps {
  readonly periods: readonly OffPlanPeriod[];
  readonly zone: string;
  /** Today in the active zone, which the declaration's date fields open on. */
  readonly today: string;
  readonly declaration: Write<OffPlanCreateBody>;
  readonly edit: Write<OffPlanEdit>;
  readonly removal: Write<OffPlanRemoval>;
}

/* Built outside the component, for the reason `SourcesPanel` states: a cell is a function the table calls per row,
 * and defining one inside a component reads to a linter as a nested component. */
function columnsFor({
  zone,
  edit,
  removal,
}: Pick<OffPlanPanelProps, "zone" | "edit" | "removal">): readonly TableColumn<OffPlanPeriod>[] {
  return [
    { key: "label", header: "Label", cell: (period) => period.label ?? "unnamed" },
    { key: "start", header: "From", cell: (period) => statedInstant(period.start, zone) },
    { key: "end", header: "To", cell: (period) => statedInstant(period.end, zone) },
    {
      key: "keep-frame",
      header: "Keeps the frame",
      cell: (period) => (
        <Checkbox
          state={period.keepFrame ? "checked" : "unchecked"}
          onStateChange={(next) =>
            void edit.submit({
              periodId: period.id,
              patch: { keepFrame: next === "checked" },
            })
          }
        >
          {period.keepFrame ? "routines run" : "nothing runs"}
        </Checkbox>
      ),
    },
    {
      key: "acts",
      header: "",
      cell: (period) => (
        <Button rank="quiet" size="sm" onClick={() => void removal.submit({ periodId: period.id })}>
          Remove
        </Button>
      ),
    },
  ];
}

export function OffPlanPanel({
  periods,
  zone,
  today,
  declaration,
  edit,
  removal,
}: OffPlanPanelProps) {
  return (
    <Panel title="Off plan" headerEnd={<span>{periods.length}</span>}>
      <p className="text-base text-ink-soft">
        {`${KEEP_FRAME_MEANINGS.off} ${KEEP_FRAME_MEANINGS.on} Either way no task, habit occurrence or ` +
          "Area slot is placed inside the span, anchors keep arriving because they are facts, and the span " +
          "leaves the budget's denominator so a holiday does not read as every Area starving."}
      </p>
      <Table
        columns={columnsFor({ zone, edit, removal })}
        rows={periods}
        rowKey={(period) => period.id}
        caption="Off-plan periods, with their spans and whether the frame survives inside them"
        countLabel={(count) =>
          count === 0
            ? "No time declared off."
            : `${count} off-plan period${count === 1 ? "" : "s"}`
        }
      />
      <Refusal problem={edit.problem ?? removal.problem} />
      <OffPlanDeclaration write={declaration} today={today} zone={zone} />
    </Panel>
  );
}
