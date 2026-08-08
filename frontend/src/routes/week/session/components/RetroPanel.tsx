/* LAST WEEK, AS THE SESSION REPORTS IT: actual against target per Area, and the days it rests on.
 *
 * COBALT ONLY, including the label cells. `DeviationBar` carries the whole rule and this panel adds none: Area ink
 * encodes identity and cobalt encodes magnitude, so a chip beside a cobalt bar would imply the bar could have been
 * Area-coloured. The Area's NAME identifies the row, which is what a name is for.
 *
 * THE DAY STATEMENT IS THE API'S OWN SENTENCE. `US-REV-04` asks that every review state its confirmed and unconfirmed
 * day counts and report off-plan days separately, and the api composes that sentence so the CLI's own review and this
 * one cannot describe the same period two ways. A period with no confirmed day says so there too, which is why this
 * panel renders the statement whatever the counts are rather than choosing between a chart and a sentence.
 *
 * A WEEK WITH NO PLAN OF RECORD HAS NO TARGETS, so there is nothing to compare and the empty state says which. That is
 * a real rendering rather than an absence: a bar chart of one row would be a chart of nothing. */

import { DeviationBar, EmptyState } from "../../../../ui/domain";
import { Panel } from "../../../../ui/layout";
import { deviationRowsOf } from "../../../areas/entries";
import { asPoints } from "../../../areas/figures";
import type { Area } from "../../../../api/hooks/useAreas";
import type { SessionRetro } from "../../../../api/hooks/useWeeklySession";

export interface RetroPanelProps {
  readonly retro: SessionRetro;
  readonly areas: readonly Area[];
}

export function RetroPanel({ retro, areas }: RetroPanelProps) {
  const rows = deviationRowsOf(retro.categories, areas, retro.discretionaryMinutes);

  return (
    <Panel
      title={`Last week · ${retro.period}`}
      headerEnd={<span className="text-eyebrow">percentage points off target</span>}
      footer={<span>{retro.statement}</span>}
    >
      {rows.length === 0 ? (
        <EmptyState
          title="Last week has no target to compare against"
          detail={
            retro.offPlanStatement ??
            "A target is a floor plus a share of the discretionary time the floors leave, so a week " +
              "with no plan of record declares none and there is nothing to compare."
          }
        />
      ) : (
        <DeviationBar
          rows={rows}
          caption="Actual against target per Area, in percentage points"
          format={asPoints}
        />
      )}
    </Panel>
  );
}
