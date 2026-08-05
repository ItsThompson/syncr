/* `/setup`: first run, as a route rather than a modal.
 *
 * A ROUTE BECAUSE CONFIGURATION SPANS SITTINGS. A reader who has to
 * connect a feed, think about their Areas, and come back tomorrow must not have that trapped in a dialog they
 * cannot leave. Progress is server state, so navigating away and back preserves it with no draft to hold.
 *
 * FOUR NUMBERED LEDGER ROWS AND NO PROGRESS BAR. `WizardSteps` draws them with a caret on the current one; a bar
 * would animate, which is refused everywhere in this product, and would say less than the rows do: which step a
 * reader is on, and which one cannot be started yet.
 *
 * TWO OF THE FOUR ARE THE MINIMUM. Areas and a day shape are what the api requires before a plan can exist, so
 * those two carry `required to solve` and the other two carry `optional`. Once both exist, the first solve runs
 * with no further prompt: nothing on this screen is a confirmation, and the root stops sending a reader here.
 *
 * THE STEPS AND THE WEEK SCREEN AGREE ON WHAT IS MISSING, because both answers come from the same reading the api
 * computes: `steps.ts` counts a day shape as declared exactly when the week pattern is, which is what
 * `POST /solve` checks before it refuses. */

import { EmptyState, ErrorState, PendingState, Plate, WizardSteps } from "../../ui/domain";
import { Pane, Panel } from "../../ui/layout";
import { Button } from "../../ui/primitives";
import { Link } from "react-router";

import { RouteBand } from "../RouteBand";
import { StepPanel } from "./components/StepPanel";
import { isCurrent, setupSteps } from "./steps";
import { useSetupReads } from "./useSetupReads";

const STATEMENT = "Four things have to exist before syncr can solve.";

export function SetupRoute() {
  const reads = useSetupReads();

  if (reads.status === "loading") {
    return (
      <RouteBand title="Setup" sub="first run">
        <PendingState
          title="Reading what you have declared so far"
          detail="Your sources, your Areas, your day shapes and the week pattern that maps them."
        />
      </RouteBand>
    );
  }

  if (reads.status === "error") {
    return (
      <RouteBand title="Setup" sub="first run">
        <ErrorState
          title="What you have declared so far could not be read"
          detail={reads.problem.detail}
        />
      </RouteBand>
    );
  }

  const steps = setupSteps(reads.data);
  const current = steps.find(isCurrent) ?? null;

  return (
    <RouteBand title="Setup" sub="first run">
      <Pane label="Setup">
        {/* The kit ships two plates, an armillary sphere and an astrolabe, and both are the instrument family the
            illustration policy names. The design sheet's own line asks for an orrery, which the kit does not have. */}
        <Plate name="armillary" fit="band" />
        <p className="text-base text-ink-soft">{STATEMENT}</p>
        <Panel title="Steps">
          <WizardSteps label="Setup steps" steps={steps} />
        </Panel>
        {current === null ? (
          <EmptyState
            title="Nothing here is outstanding"
            detail={
              "All four steps are done, so the plan has everything it needs and the first solve runs with " +
              "no further prompt from this screen."
            }
            action={
              <Button asChild rank="secondary">
                <Link to="/week">Go to the week</Link>
              </Button>
            }
          />
        ) : (
          <StepPanel step={current} />
        )}
      </Pane>
    </RouteBand>
  );
}
