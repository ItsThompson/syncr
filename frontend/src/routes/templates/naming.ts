/* Turning an identifier into the name a reader recognises.
 *
 * NOTHING HERE INVENTS A NAME. Whether a binding still resolves is the shape read's own answer (`contentResolves`);
 * this module only supplies the NAME behind a binding that does, so one lookup serves both the entry column and
 * the editor's select. An entry whose row is gone is rendered from the report, not from a null here.
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
