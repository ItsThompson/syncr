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
 * A BLOCKED STEP OFFERS NO LINK. Its own predecessor is what a reader has to do next, and a control that led to a
 * screen where the work cannot be done yet would be an invitation to fail. */

import { Link } from "react-router";

import { Panel } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import type { SetupStep } from "../steps";

export interface StepPanelProps {
  readonly step: SetupStep;
}

export function StepPanel({ step }: StepPanelProps) {
  return (
    <Panel title={step.label} headerEnd={<span>{step.note}</span>}>
      <p className="text-base text-ink-soft">{step.statement}</p>
      {step.status === "blocked" ? (
        <p className="text-sm text-text-muted">
          {`This step cannot be started yet: ${step.note}.`}
        </p>
      ) : (
        <div>
          <Button asChild rank="secondary">
            <Link to={step.href}>{step.actionLabel}</Link>
          </Button>
        </div>
      )}
    </Panel>
  );
}
