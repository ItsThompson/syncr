/* How the Learned screen reads a parameter: its name, its figure, and how much of it is still the prior.
 *
 * THE NAME IS THE API'S TOKEN, HUMANISED, JOINED TO THE SERVED SUBJECT. `duration_multiplier[<uuid>]`
 * becomes `Duration multiplier`; what its key is about is the api's word rather than this module's: the row
 * carries it as `subject`, resolved from the key server-side, and both strings the row gives a reader -- the
 * name column's label and the unlock meter's accessible name -- are that token joined to the subject, so rows
 * carrying one parameter for different Areas never read as one. The row's own sentence states it in prose as
 * well: `You estimate 60m for Fitness; your actual median is 82m`. Reading a label out of a UUID is
 * not something a client can do, and inventing one would put a second name for one Area on one screen.
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

/** U+00B7 MIDDLE DOT, which is how this screen joins a thing to what it is about. */
const JOIN = "\u00b7";

/** A learned row's name: the humanised token, joined to the served subject where the key carries one.
 *
 * Nothing stands in for an absent subject, because a parameter with no key is about the whole account rather
 * than about an Area: the humanised token alone is then the whole name, not a placeholder waiting for one. */
export function rowLabel(parameter: string, subject: string | null): string {
  if (subject === null) return parameterName(parameter);
  return `${parameterName(parameter)} ${JOIN} ${subject}`;
}

/** The fitted figure, or the em dash a parameter below its gate has instead of one. */
export function asValue(value: number | null): string {
  return value === null ? NOTHING : value.toFixed(VALUE_PLACES);
}

/** A share of one as a whole percentage: `0.42` reads `42%`. */
export function asShare(share: number): string {
  return `${Math.round(share * PERCENT)}%`;
}

/** A count of samples against what it needs, for the meter's accessible name.
 *
 * The subject is part of the name so same-parameter rows do not share one: twelve meters must give a screen
 * reader twelve names, which they cannot do if every one of them announces only the parameter token. A keyless
 * parameter has no subject to name and none is invented. */
export function progressLabel(parameter: string, subject: string | null): string {
  const base = `${parameterName(parameter)} unlock progress`;
  return subject === null ? base : `${base} for ${subject}`;
}
