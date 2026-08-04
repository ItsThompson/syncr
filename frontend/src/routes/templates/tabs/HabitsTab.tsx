/* Habits: the table, the two derivations, and the editor.
 *
 * THE RAMP READING TRAVELS WITH THE AREAS AND IS RENDERED WHERE THE CHIPS ARE. Past twelve Areas the pigment
 * repeats, so two chips in this table can be the same ink; the api states that in a sentence and this panel's
 * footer carries it. Hiding it would leave a reader trusting a chip that no longer identifies anything, and the
 * frontend cannot fix it on its own: the wire carries the ramp step, not the position in the deal.
 *
 * THE EDITOR IS KEYED BY THE SELECTED HABIT, so choosing another habit mounts a fresh draft. Without the key a
 * reader would see one habit's title under another's name until they touched the field. */

import { EmptyState, PendingState } from "../../../ui/domain";
import { Panel, Pane } from "../../../ui/layout";
import { readingOf } from "../../reading";
import { HabitDerivations } from "../components/HabitDerivations";
import { HabitEditor } from "../components/HabitEditor";
import { HabitTable } from "../components/HabitTable";
import { ReadFailure } from "../components/ReadFailure";
import type { Resource } from "../../../contract";
import type { Areas } from "../../../api/hooks/useAreas";
import type { Habit, HabitEdit } from "../../../api/hooks/useHabits";
import type { Write } from "../../../api/hooks/useWrite";

export interface HabitsTabProps {
  readonly habits: Resource<readonly Habit[]>;
  readonly areas: Resource<Areas>;
  readonly selectedId: string | null;
  readonly onSelect: (habitId: string) => void;
  readonly write: Write<HabitEdit>;
}

export function HabitsTab({ habits, areas, selectedId, onSelect, write }: HabitsTabProps) {
  const reading = readingOf({ habits, Areas: areas });

  if (reading.status === "loading") {
    return (
      <PendingState
        title="Reading your habits"
        detail="Each habit's cadence, its debt figure, and the Area its occurrences count toward."
      />
    );
  }
  if (reading.status === "error") {
    return (
      <ReadFailure title={`The ${reading.name} could not be read`} problem={reading.problem} />
    );
  }

  const { habits: habitList, Areas: areaReading } = reading.data;

  if (habitList.length === 0) {
    return (
      <EmptyState
        title="No habit is declared"
        detail={
          "A habit is a recurring intention with a cadence, so syncr generates its occurrences without " +
          "any per-occurrence authoring. Declaring one is how `four times a week` gets said once."
        }
      />
    );
  }

  const selected = habitList.find((habit) => habit.id === selectedId) ?? null;

  return (
    <div className="flex flex-wrap items-start gap-3.25">
      <Pane label="The habits list">
        <Panel
          title="Habits"
          headerEnd={<span className="text-eyebrow">rules on cadence, never on a template</span>}
          /* Null until two Areas hold one step, and `undefined` is what draws no footer at all: `Panel`
           * renders the element for any defined value, so a null would leave an empty band under the table. */
          footer={areaReading.ramp.statement ?? undefined}
        >
          <HabitTable
            habits={habitList}
            areas={areaReading.areas}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        </Panel>
      </Pane>
      <Pane label="The selected habit">
        {selected === null ? (
          <EmptyState
            title="No habit is selected"
            detail="Choose a habit from the table to read its derivations and change it."
          />
        ) : (
          <>
            <Panel title="Derived, and read-only">
              <HabitDerivations habit={selected} />
            </Panel>
            <Panel title={`Edit ${selected.title}`}>
              <HabitEditor key={selected.id} habit={selected} write={write} />
            </Panel>
          </>
        )}
      </Pane>
    </div>
  );
}
