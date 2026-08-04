/* Which table a concrete entry's binding names, carried through one `<select>` value.
 *
 * A routine and a habit live in separate tables with no shared parent, so the identifier alone does not say
 * which to read: the api takes `bindingTarget` beside `bindingRef` for exactly that reason. A select hands
 * back one string, so the two travel as `routine:<id>` and the parse is here rather than inline at the
 * control, where a second surface offering the same choice would spell it differently.
 *
 * AN UNRECOGNISED VALUE IS NULL, NOT A GUESS. Probing both tables is what the discriminator exists to
 * prevent, and defaulting to `routine` would make a habit's identifier read as a routine's. */

import type { components } from "../../api/schema";

export type BindingTarget = components["schemas"]["BindingTarget"];

export interface BindingChoice {
  readonly target: BindingTarget;
  readonly ref: string;
}

const TARGETS: readonly BindingTarget[] = ["routine", "habit"];

const SEPARATOR = ":";

/** The select value for one choice: `routine:0f2c…`. */
export function bindingValue(choice: BindingChoice): string {
  return `${choice.target}${SEPARATOR}${choice.ref}`;
}

/** The choice a select value names, or null when it names none. */
export function bindingFrom(value: string): BindingChoice | null {
  const separator = value.indexOf(SEPARATOR);
  if (separator === -1) return null;
  const target = value.slice(0, separator);
  const ref = value.slice(separator + 1);
  if (ref === "") return null;
  const known = TARGETS.find((candidate) => candidate === target);
  if (known === undefined) return null;
  return { target: known, ref };
}
