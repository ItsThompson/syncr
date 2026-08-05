/* The sleep routine, and the bounds its floor may take.
 *
 * THIS SCREEN'S CONTROL IS A SHORTCUT AND NOT A HOME. The sleep floor is `minDurationMinutes` on the sleep
 * routine and it is set through `PATCH /api/v1/routines/{id}`: there is no settings field for it, the solver
 * reads it from the domain, and `SettingsPatchRequest` rejects an unknown member, so sending it to the settings
 * endpoint would be a stated 422 rather than a value quietly stored in two places. What this screen adds is
 * where a reader expects to find it.
 *
 * THE ROUTINE IS FOUND BY ITS TITLE, because nothing on a routine marks one as the sleep routine. Two routines
 * may legitimately share a title, so the FIRST match is the one, which is the same order the list is read in.
 * A tenant with no routine so titled has no floor to set, and the panel says so rather than offering a control
 * with nothing behind it.
 *
 * THE CEILING IS THE TARGET DURATION. The api refuses a floor above it, because a routine that could be
 * compressed past its own target would make the target meaningless, and `reduce_routine` is offered only for a
 * routine whose floor is BELOW its target. A floor equal to the target is the default for every routine and is
 * what makes one incompressible. */

import type { Routine } from "../../api/hooks/useRoutines";

/** The title the sleep routine carries, compared case-insensitively and trimmed. */
const SLEEP_TITLE = "sleep";

/** The smallest floor the api accepts. A routine with a floor of zero would not be a span. */
export const MIN_FLOOR_MINUTES = 1;

/** The first routine titled `Sleep`, or null when the tenant has declared none. */
export function sleepRoutineOf(routines: readonly Routine[]): Routine | null {
  return routines.find((routine) => routine.title.trim().toLowerCase() === SLEEP_TITLE) ?? null;
}

/** True when the solver may propose spending sleep, which is exactly when the floor is below the target. */
export function isElastic(routine: Routine): boolean {
  return routine.minDurationMinutes < routine.durationMinutes;
}
