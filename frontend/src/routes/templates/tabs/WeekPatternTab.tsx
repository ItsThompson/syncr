/* The week pattern: which day type each weekday uses.
 *
 * A 404 IS AN ANSWER HERE, so `null` is a state this tab draws rather than an error it reports: before a
 * pattern is declared the table reads `not declared` on all seven rows and the editor starts empty. The
 * alternative, an error surface, would tell a first-run reader that something is broken when nothing is.
 *
 * NO DAY TYPES AT ALL IS THE ONE EMPTY CASE, because a mapping needs something to map to. It points at setup,
 * which is where the first day type and the first shape are declared. */

import { EmptyState, PendingState } from "../../../ui/domain";
import { Panel, Pane } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import { SETUP_PATH } from "../../../ui/domain/shell/navigation";
import { Link } from "react-router";

import { readingOf } from "../../reading";
import { PatternEditor } from "../components/PatternEditor";
import { PatternTable } from "../components/PatternTable";
import { ReadFailure } from "../components/ReadFailure";
import type { Resource } from "../../../contract";
import type { DayType } from "../../../api/hooks/useTemplates";
import type { WeekPattern, WeekPatternBody } from "../../../api/hooks/useWeekPattern";
import type { Write } from "../../../api/hooks/useWrite";

export interface WeekPatternTabProps {
  readonly pattern: Resource<WeekPattern | null>;
  readonly dayTypes: Resource<readonly DayType[]>;
  readonly write: Write<WeekPatternBody>;
}

export function WeekPatternTab({ pattern, dayTypes, write }: WeekPatternTabProps) {
  const reading = readingOf({ "week pattern": pattern, "day types": dayTypes });

  if (reading.status === "loading") {
    return (
      <PendingState
        title="Reading your week pattern"
        detail="The mapping from weekday to day type, and the day types it can name."
      />
    );
  }
  if (reading.status === "error") {
    return (
      <ReadFailure title={`The ${reading.name} could not be read`} problem={reading.problem} />
    );
  }

  const { "week pattern": declared, "day types": dayTypeList } = reading.data;

  if (dayTypeList.length === 0) {
    return (
      <EmptyState
        title="No day type is declared"
        detail={
          "A week pattern maps each weekday to a kind of day, so there has to be a kind of day to map " +
          "to. Setup declares the first one, along with the shape it uses."
        }
        action={
          <Button asChild rank="secondary">
            <Link to={SETUP_PATH}>Go to setup</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-wrap items-start gap-3.25">
      <div className="w-sidebar shrink-0">
        <Panel title="Week pattern">
          <PatternTable pattern={declared} dayTypes={dayTypeList} />
        </Panel>
      </div>
      <Pane label="Declaring the week pattern">
        <PatternEditor pattern={declared} dayTypes={dayTypeList} write={write} />
      </Pane>
    </div>
  );
}
