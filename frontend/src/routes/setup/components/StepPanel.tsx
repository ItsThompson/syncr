/* The current step's own panel: what the step asks for, why, and where it is authored.
 *
 * SETUP IS A LEDGER OF READINESS, NOT A SECOND AUTHORING SURFACE, and that is the decision this component embodies.
 * Areas are authored on `/areas`, day shapes and the week pattern on `/templates`, sources and the day bounds and
 * the write target on `/settings`. A wizard that drew its own forms for those would be a second home for four
 * values, and the day one of them gained a field the wizard's copy would be the one that stayed behind.
 *
 * LEAVING IS THE POINT RATHER THAN A COST. Setup is a route because configuration spans sittings: a reader follows
 * the link, declares the thing on the screen that owns it, and comes back to a ledger whose caret has moved. That
 * is the same act on the second sitting as on the first, which is what makes it resumable with no draft to keep.
 *
 * A PANEL IS ONLY EVER DRAWN FOR THE CURRENT STEP, and the prop's type says so. A blocked step cannot be the
 * current one, because the caret is promoted from a WAITING status and a blocked step is neither: the ledger row is
 * where a blocked step is read, and it offers nothing to follow. Taking `CurrentSetupStep` rather than `SetupStep`
 * is what keeps that from being a branch here that no reader can reach. */

import { Link } from "react-router";

import { Panel } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import type { CurrentSetupStep } from "../steps";

export interface StepPanelProps {
  readonly step: CurrentSetupStep;
}

export function StepPanel({ step }: StepPanelProps) {
  return (
    <Panel title={step.label} headerEnd={<span>{step.note}</span>}>
      <p className="text-base text-ink-soft">{step.statement}</p>
      <div>
        <Button asChild rank="secondary">
          <Link to={step.href}>{step.actionLabel}</Link>
        </Button>
      </div>
    </Panel>
  );
}
