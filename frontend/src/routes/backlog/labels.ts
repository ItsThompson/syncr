/* THE BACKLOG'S READING: the words the header states, the sentence under the table, and each cell's figure.
 *
 * HERE RATHER THAN IN THE COMPONENTS, so the two figures the header states and the footer's count are one
 * vocabulary, and so a test can drive the sentence without rendering a screen.
 *
 * A DEADLINE IS READ IN THE READER'S OWN ZONE, which is why the function taking one takes the zone too. An
 * instant formatted in the host's zone would put a deadline on the wrong day for a reader who is travelling,
 * and the whole point of the column is which day the work is due. */

import { wallOf } from "../../lib/zonedInstant";
import type { BacklogHeader, BacklogTask } from "../../api/hooks/useBacklog";

/** What a cell says where the task carries no value for it. */
export const NOTHING = "\u00b7";

/** The band's own sentence: the two figures the server states, never a count of the rows on screen. */
export function headerReading(header: BacklogHeader): string {
  const open = `${header.openCount} open`;
  return header.atRiskCount === 0 ? open : `${open} \u00b7 ${header.atRiskCount} at risk`;
}

/**
 * The footer's sentence, given how many rows were drawn.
 *
 * The footer counts the ROWS and the band counts the backlog, which is why the two are different sentences: a
 * filtered table shows fewer rows than there are open tasks, and both figures are true.
 */
export function footerReading(count: number): string {
  return count === 1 ? "1 row" : `${count} rows`;
}

/** A deadline as a date and a clock time in the reader's zone, or the empty reading for a task with none. */
export function deadlineReading(deadline: string | null, zone: string): string {
  if (deadline === null) return NOTHING;
  const wall = wallOf(deadline, zone);
  return wall === null ? NOTHING : `${wall.date} ${wall.time}`;
}

/** A duration in the units the backlog compares: minutes under an hour, hours and minutes above it. */
export function minutesReading(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
}

/** What the physics column says: whether the solver may divide the task, and the floor if it may. */
export function chunkReading(task: BacklogTask): string {
  return task.splittable ? `\u2265 ${minutesReading(task.minChunkMinutes)}` : "atomic";
}
