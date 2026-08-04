/* Day shapes: the list, the selected shape's entries, and the editor that declares one.
 *
 * SIX READS FEED THIS TAB and every one of them is needed to draw a row: an entry names a routine, a habit or
 * an Area, and rendering an identifier where a name belongs is not a degraded rendering, it is an unreadable
 * one. So the tab draws when all six are ready and says which one failed when one did.
 *
 * THE EMPTY CASE IS THE FIRST-RUN CASE, and it points at setup rather than offering a form. A day shape is one
 * of the two things that have to exist before a week can be solved, and setup is where that minimum is built:
 * a second place to declare the first shape would be a second answer to "what do I do first". */

import { Link } from "react-router";

import { EmptyState, PendingState } from "../../../ui/domain";
import { Panel, Pane } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import { SETUP_PATH } from "../../../ui/domain/shell/navigation";
import { readingOf } from "../../reading";
import { EntryEditor } from "../components/EntryEditor";
import { EntryTable } from "../components/EntryTable";
import { ReadFailure } from "../components/ReadFailure";
import { ShapeList } from "../components/ShapeList";
import type { Resource } from "../../../contract";
import type { Areas } from "../../../api/hooks/useAreas";
import type { Habit } from "../../../api/hooks/useHabits";
import type { Routine } from "../../../api/hooks/useRoutines";
import type {
  DayShape,
  DayShapeSummary,
  DayType,
  EntryBody,
} from "../../../api/hooks/useTemplates";
import type { Write } from "../../../api/hooks/useWrite";

export interface DayShapesTabProps {
  readonly shapes: Resource<readonly DayShapeSummary[]>;
  readonly dayTypes: Resource<readonly DayType[]>;
  readonly areas: Resource<Areas>;
  readonly routines: Resource<readonly Routine[]>;
  readonly habits: Resource<readonly Habit[]>;
  /** The shape the editor is showing, or null when the tenant has none. */
  readonly shape: Resource<DayShape | null>;
  readonly selectedId: string | null;
  readonly onSelect: (templateId: string) => void;
  readonly entryWrite: Write<EntryBody>;
}

export function DayShapesTab({
  shapes,
  dayTypes,
  areas,
  routines,
  habits,
  shape,
  selectedId,
  onSelect,
  entryWrite,
}: DayShapesTabProps) {
  const reading = readingOf({
    "day shapes": shapes,
    "day types": dayTypes,
    Areas: areas,
    routines,
    habits,
    "selected shape": shape,
  });

  if (reading.status === "loading") {
    return (
      <PendingState
        title="Reading your day shapes"
        detail="The list, the selected shape's entries, and the Areas an entry can name."
      />
    );
  }
  if (reading.status === "error") {
    return (
      <ReadFailure title={`The ${reading.name} could not be read`} problem={reading.problem} />
    );
  }

  const {
    "day shapes": shapeList,
    "day types": dayTypeList,
    Areas: areaReading,
    routines: routineList,
    habits: habitList,
    "selected shape": selected,
  } = reading.data;

  if (shapeList.length === 0) {
    return (
      <EmptyState
        title="No day shape is declared"
        detail={
          "A day shape is what syncr materializes for every date the week pattern maps to its day type, " +
          "so until one exists there is nothing to lay out. Setup builds the first one."
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
        <Panel title="Day shapes">
          <ShapeList
            shapes={shapeList}
            dayTypes={dayTypeList}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        </Panel>
      </div>
      <Pane label="The selected day shape">
        {selected === null ? (
          <EmptyState
            title="No shape is selected"
            detail="Choose a shape from the list to read its entries and declare another."
          />
        ) : (
          <Panel
            title={selected.name}
            headerEnd={<span className="text-eyebrow">{selected.entries.length} entries</span>}
          >
            <EntryTable
              entries={selected.entries}
              areas={areaReading.areas}
              routines={routineList}
              habits={habitList}
            />
          </Panel>
        )}
        <Panel title="Declare an entry">
          <EntryEditor
            areas={areaReading.areas}
            routines={routineList}
            habits={habitList}
            write={entryWrite}
          />
        </Panel>
      </Pane>
    </div>
  );
}
