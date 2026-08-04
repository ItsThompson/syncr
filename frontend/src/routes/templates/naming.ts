/* Turning an identifier into the name a reader recognises.
 *
 * NOTHING HERE INVENTS A NAME. A binding whose routine or habit is no longer declared answers null, and the
 * cell says so, because the api does not check that a concrete entry's binding names a row that exists: the
 * routines and habits tables did not exist when the entry shape was declared, and validating it is still
 * open. An entry naming a removed routine is therefore reachable, and rendering its bare identifier or an
 * empty cell would both read as a rendering fault rather than as the missing row it is.
 *
 * Pure: no React, no client, no DOM. */

import type { Area } from "../../api/hooks/useAreas";
import type { Habit } from "../../api/hooks/useHabits";
import type { Routine } from "../../api/hooks/useRoutines";
import type { TemplateEntry } from "../../api/hooks/useTemplates";

/** The Area an identifier names, or null when this tenant holds no such Area. */
export function areaOf(areas: readonly Area[], areaId: string | null): Area | null {
  if (areaId === null) return null;
  return areas.find((area) => area.id === areaId) ?? null;
}

/** The content a concrete entry names, or null for a slot and for a binding whose row is gone. */
export function bindingNameOf(
  entry: TemplateEntry,
  routines: readonly Routine[],
  habits: readonly Habit[],
): string | null {
  if (entry.bindingRef === null) return null;
  if (entry.bindingTarget === "routine") {
    return routines.find((routine) => routine.id === entry.bindingRef)?.title ?? null;
  }
  if (entry.bindingTarget === "habit") {
    return habits.find((habit) => habit.id === entry.bindingRef)?.title ?? null;
  }
  return null;
}
