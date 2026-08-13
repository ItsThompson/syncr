/* `/backlog`: the tasks and projects, and the capture that reaches them from anywhere.
 *
 * COMPOSITION ONLY. The state, the two reads and the write are `useBacklogScreen`'s; what is here is which
 * surface each reading draws.
 *
 * THE HEADER'S TWO FIGURES ARE THE SERVER'S. `openCount` and `atRiskCount` are computed over the Area's open
 * tasks, so they state the backlog while the table's footer states the rows on screen. At risk in particular is
 * the week verdict's own determination: the same shortfall the verdict panel renders, so a task cannot be at
 * risk on one screen and fine on another, and nothing in the frontend compares a deadline against a capacity.
 *
 * EVERY STATE IS STATIC. There is no spinner, no skeleton and nothing to spin with: a pending surface says what
 * it is waiting for in words. The empty state carries the capture prompt, because a backlog with nothing in it
 * is an invitation rather than a dead end.
 *
 * THE EMPTY STATE'S PROMPT NAMES THE BAND'S CONTROL AS WHERE FOCUS RETURNS, and that is not a detail: capturing
 * the first task replaces the prompt with a table, so the button the reader pressed is gone before the dialog
 * closes and returning to it would return to nowhere. The band's control is the same affordance and survives.
 *
 * CAPTURE IS NOT MOUNTED HERE. `n` opens it from any screen, so the one instance lives above the route in
 * `app/capture`; this screen asks that instance to open. A second dialog mounted here would mean two forms could
 * hold two drafts of the same task.
 *
 * AND IT IS ASKED TO OPEN BY THE URL AS WELL AS BY THE BAND. Activating an empty slot's gutter label on the week
 * screen navigates here with what that slot knows, so this screen reads the invitation and clears it. That read is
 * above every early return below, because capture is the shell's and not this screen's: a reader whose backlog
 * could not be read must still be able to capture the task they came here to write. */

import { useRef } from "react";

import { useCapture, useCapturePrefill } from "../../app/capture";
import { EmptyState, ErrorState, PendingState, type Notice } from "../../ui/domain";
import { Button } from "../../ui/primitives";
import { RouteBand } from "../RouteBand";
import { BacklogBand } from "./components/BacklogBand";
import { BacklogFilters } from "./components/BacklogFilters";
import { BacklogTable } from "./components/BacklogTable";
import { headerReading } from "./labels";
import { completionRefusedNotice, taskCompletedNotice } from "./notices";
import { useBacklogScreen } from "./useBacklogScreen";

const SUB = "tasks and projects";

export function BacklogRoute() {
  const screen = useBacklogScreen();
  const capture = useCapture();
  const bandCapture = useRef<HTMLButtonElement>(null);
  const { reading } = screen;

  useCapturePrefill();

  if (reading.status === "loading") {
    return (
      <RouteBand sub={SUB} title="Backlog">
        <PendingState
          detail="The tasks, their physics, and which of them this week's verdict names."
          title="Reading the backlog"
        />
      </RouteBand>
    );
  }

  if (reading.status === "error") {
    return (
      <RouteBand sub={SUB} title="Backlog">
        <ErrorState
          detail={reading.problem.detail}
          title={`The ${screen.failed ?? "backlog"} could not be read`}
        />
      </RouteBand>
    );
  }

  const { backlog, rows, areas } = reading.data;
  const notices: Notice[] = [];
  if (screen.completionRefusal !== null) {
    notices.push(completionRefusedNotice(screen.completionRefusal));
  } else if (screen.completed !== null) {
    notices.push(taskCompletedNotice(screen.completed));
  }

  return (
    <RouteBand sub={`${SUB} · ${headerReading(backlog.header)}`} title="Backlog">
      <div className="flex flex-col gap-3.25">
        <BacklogBand
          captureRef={bandCapture}
          header={backlog.header}
          notices={notices}
          onCapture={() => capture.open()}
        />
        <BacklogFilters
          areas={[...areas].map(([id, area]) => ({ id, name: area.name }))}
          filters={screen.filters}
          onFiltersChange={screen.onFiltersChange}
        />
        {rows.length === 0 ? (
          <EmptyState
            action={
              capture.isAvailable ? (
                <Button onClick={() => capture.open({ returnFocusTo: bandCapture.current })}>
                  Capture the first one
                </Button>
              ) : undefined
            }
            detail={
              "Nothing here answers the filters above. Capture a task with a title and an Area and the next " +
              "solve can place it: press n from any screen, and everything else already has a default."
            }
            title="No task is in this list"
          />
        ) : (
          <BacklogTable
            areas={areas}
            nowMs={screen.nowMs}
            onComplete={screen.onComplete}
            onSortChange={screen.onSortChange}
            sort={screen.sort}
            tasks={rows}
            zone={screen.zone}
          />
        )}
      </div>
    </RouteBand>
  );
}
