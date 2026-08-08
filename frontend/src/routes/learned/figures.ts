/* How the Learned screen reads a parameter: its name, its figure, and how much of it is still the prior.
 *
 * THE NAME IS THE API'S TOKEN, HUMANISED AND NOTHING MORE. `duration_multiplier[<uuid>]` becomes
 * `Duration multiplier`, and the Area the key names is carried by the row's own sentence, which is where the
 * api put it: `You estimate 60m for Fitness; your actual median is 82m`. Reading a label out of a UUID is
 * not something a client can do, and inventing one would put a second name for one Area on one screen.
 * `tickets/1551` holds whether the key should arrive named.
 *
 * THE FIGURES ARE THIS SCREEN'S OWN, NOT THE AREAS SCREEN'S. `asPercent` there is a share of discretionary
 * time already scaled to a hundred; a shrinkage weight is a share of ONE, and passing it through the other
 * would print `0.4%` for a value that is 40% prior. Two different quantities, two functions, each stated
 * where its own reader is.
 *
 * A COLLECTING PARAMETER HAS NO VALUE AND THAT IS THE GATE. Below its threshold a parameter is not applied at
 * all, so the api sends no figure, and the cell reads as the same nothing every other table in this product
 * spells with an em dash rather than as a zero a reader could compare. */

/** U+2014 EM DASH, which is how every table in this product spells a cell with nothing in it. */
const NOTHING = "\u2014";

const PERCENT = 100;
/** Two places on a fitted multiplier, which is the resolution a shrunk estimate actually differs at. */
const VALUE_PLACES = 2;

/** `duration_multiplier[<uuid>]` as a reader meets it: `Duration multiplier`.
 *
 * The key is dropped rather than split off, because a name with no key is the common case and a
 * fallback for a split that cannot fail would be a branch nothing can enter. */
export function parameterName(parameter: string): string {
  const spaced = parameter.replace(/\[.*$/, "").replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** The fitted figure, or the em dash a parameter below its gate has instead of one. */
export function asValue(value: number | null): string {
  return value === null ? NOTHING : value.toFixed(VALUE_PLACES);
}

/** A share of one as a whole percentage: `0.42` reads `42%`. */
export function asShare(share: number): string {
  return `${Math.round(share * PERCENT)}%`;
}

/** A count of samples against what it needs, for the meter's accessible name. */
export function progressLabel(parameter: string): string {
  return `${parameterName(parameter)} unlock progress`;
}
