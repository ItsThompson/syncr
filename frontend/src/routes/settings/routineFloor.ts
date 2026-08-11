/* A routine's floor, and the bounds it may take.
 *
 * THIS SCREEN'S CONTROL IS A SHORTCUT AND NOT A HOME. A floor is `minDurationMinutes` on the routine it belongs to
 * and it is set through `PATCH /api/v1/routines/{id}`: there is no settings field for it, the solver reads it from
 * the domain, and `SettingsPatchRequest` rejects an unknown member, so sending it to the settings endpoint would be
 * a stated 422 rather than a value quietly stored in two places. What this screen adds is where a reader expects to
 * find it.
 *
 * EVERY ROUTINE HAS A FLOOR AND NONE OF THEM IS NAMED HERE. `RoutineResponse` carries no marker singling one
 * routine out, and the domain has no rule keyed to one either: `minDurationMinutes < durationMinutes` is the whole
 * of what makes a routine one the solver may propose shortening, whatever the routine is called. Two routines may
 * legitimately share a title, so a title identifies nothing and this module does not read one.
 *
 * THE CEILING IS THE TARGET DURATION. The api refuses a floor above it, because a routine that could be compressed
 * past its own target would make the target meaningless, and `reduce_routine` is offered only for a routine whose
 * floor is BELOW its target. A floor equal to the target is the default for every routine and is what makes one
 * incompressible. */

import type { Routine } from "../../api/hooks/useRoutines";

/** The smallest floor the api accepts. A routine with a floor of zero would not be a span. */
export const MIN_FLOOR_MINUTES = 1;

/** True when the solver may propose shortening this routine, which is exactly when the floor is below the target. */
export function isElastic(routine: Routine): boolean {
  return routine.minDurationMinutes < routine.durationMinutes;
}
