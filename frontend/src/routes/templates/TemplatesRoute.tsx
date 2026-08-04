/* `/templates`: the authoring surface for day shapes, the week pattern, habits and anchor types.
 *
 * FOUR TABS, ONE SCREEN, AND THE READS BELONG TO THE ROUTE. Every read on this screen happens here and every
 * component below takes its data as props, so each tab is testable without a network fixture and no component
 * fetches. What the route owns beyond the reads is the three selections and the tab, which are the only state
 * this screen has.
 *
 * A TAB'S READS ARE ITS OWN. The tab component narrows its own resources, so a failure reading the commitments
 * does not blank the day shapes: they are four surfaces over four collections, and a screen that waited for all
 * of them would be as slow as its slowest read and as broken as its most broken one.
 *
 * THE SELECTION FALLS BACK TO THE FIRST ROW rather than being assigned by an effect. A screen that set its own
 * selection after the list arrived would render once with nothing selected and again with something, which on a
 * surface with no animation is a visible flicker. Derived, it renders once.
 *
 * THE TAB IS LOCAL STATE, NOT A URL PARAMETER. A mode is reachable by URL because a mode is a way of using a
 * screen; a tab is which of four lists is in front, and the screen is the destination either way. */

import { useState } from "react";

import { Tabs } from "../../ui/primitives";
import {
  useAnchorTypeEdit,
  useAnchorTypeOrder,
  useAnchorTypes,
} from "../../api/hooks/useAnchorTypes";
import { useAnchors } from "../../api/hooks/useAnchors";
import { useAreas } from "../../api/hooks/useAreas";
import { useHabitEdit, useHabits } from "../../api/hooks/useHabits";
import { useRoutines } from "../../api/hooks/useRoutines";
import { useCalendarSources } from "../../api/hooks/useCalendarSources";
import {
  useDayShape,
  useDayShapes,
  useDayTypes,
  useEntryDeclaration,
} from "../../api/hooks/useTemplates";
import { useWeekPattern, useWeekPatternDeclaration } from "../../api/hooks/useWeekPattern";
import { RouteBand } from "../RouteBand";
import { AnchorTypesTab } from "./tabs/AnchorTypesTab";
import { DayShapesTab } from "./tabs/DayShapesTab";
import { HabitsTab } from "./tabs/HabitsTab";
import { WeekPatternTab } from "./tabs/WeekPatternTab";
import { movedEarlier, movedLater } from "./order";
import { fortnightFrom } from "./span";
import type { Resource } from "../../contract";

/** A tab's count, or absent while its list has not arrived. Zero is a count and renders as one. */
function countOf(resource: Resource<readonly unknown[]>): number | undefined {
  return resource.status === "ready" ? resource.data.length : undefined;
}

function firstIdOf(resource: Resource<readonly { readonly id: string }[]>): string | null {
  return resource.status === "ready" ? (resource.data.at(0)?.id ?? null) : null;
}

export function TemplatesRoute() {
  const [tab, setTab] = useState("day-shapes");
  const [chosenShapeId, setChosenShapeId] = useState<string | null>(null);
  const [chosenHabitId, setChosenHabitId] = useState<string | null>(null);
  const [chosenTypeId, setChosenTypeId] = useState<string | null>(null);
  /* Held still for as long as the screen is open, because the span is half of the commitments cache key. */
  const [span] = useState(() => fortnightFrom(new Date()));
  const [timeZone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);

  const dayTypes = useDayTypes();
  const shapes = useDayShapes();
  const areas = useAreas();
  const routines = useRoutines();
  const habits = useHabits();
  const pattern = useWeekPattern();
  const anchorTypes = useAnchorTypes();
  const sources = useCalendarSources();
  const anchors = useAnchors(span.from, span.to);

  const selectedShapeId = chosenShapeId ?? firstIdOf(shapes);
  const selectedHabitId = chosenHabitId ?? firstIdOf(habits);
  const selectedTypeId = chosenTypeId ?? firstIdOf(anchorTypes);

  const shape = useDayShape(selectedShapeId);
  const entryWrite = useEntryDeclaration(selectedShapeId);
  const patternWrite = useWeekPatternDeclaration();
  const habitWrite = useHabitEdit(selectedHabitId);
  const anchorTypeWrite = useAnchorTypeEdit(selectedTypeId);
  const orderWrite = useAnchorTypeOrder();

  const currentOrder =
    anchorTypes.status === "ready" ? anchorTypes.data.map((type) => type.id) : [];
  const reorder = (next: readonly string[]) => {
    /* A move past either end answers with the same order, and sending it would be a write that changes
     * nothing while re-evaluating every commitment. */
    if (next === currentOrder) return;
    void orderWrite.submit({ anchorTypeIds: [...next] });
  };

  return (
    <RouteBand
      title="Templates"
      sub="define a day shape once, and syncr materializes it every week. Cadence lives on habits"
    >
      <Tabs
        label="Templates"
        value={tab}
        onValueChange={setTab}
        tabs={[
          {
            value: "day-shapes",
            label: "Day shapes",
            count: countOf(shapes),
            content: (
              <DayShapesTab
                shapes={shapes}
                dayTypes={dayTypes}
                areas={areas}
                routines={routines}
                habits={habits}
                shape={shape}
                selectedId={selectedShapeId}
                onSelect={setChosenShapeId}
                entryWrite={entryWrite}
              />
            ),
          },
          {
            value: "week-pattern",
            label: "Week pattern",
            content: <WeekPatternTab pattern={pattern} dayTypes={dayTypes} write={patternWrite} />,
          },
          {
            value: "habits",
            label: "Habits",
            count: countOf(habits),
            content: (
              <HabitsTab
                habits={habits}
                areas={areas}
                selectedId={selectedHabitId}
                onSelect={setChosenHabitId}
                write={habitWrite}
              />
            ),
          },
          {
            value: "anchor-types",
            label: "Anchor types",
            count: countOf(anchorTypes),
            content: (
              <AnchorTypesTab
                types={anchorTypes}
                areas={areas}
                sources={sources}
                anchors={anchors}
                selectedId={selectedTypeId}
                onSelect={setChosenTypeId}
                onMoveEarlier={(id) => reorder(movedEarlier(currentOrder, id))}
                onMoveLater={(id) => reorder(movedLater(currentOrder, id))}
                write={anchorTypeWrite}
                timeZone={timeZone}
              />
            ),
          },
        ]}
      />
    </RouteBand>
  );
}
