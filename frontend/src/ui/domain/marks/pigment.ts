/* THE AREA RAMP'S STEPS, AND WHICH ONE AN ASSIGNED INDEX LANDS ON.
 *
 * This is domain truth rather than a component's business: the Areas screen, the legend, the pie chart and the week
 * grid each need to turn an Area's `pigment_index` into a ramp step, and none of them should have to import a chip
 * to ask. It sits beside `occupant.ts` for the same reason that file exists: the glyph slot's precedence is a fact
 * about the product, not about the component that happens to draw it.
 *
 * A PIGMENT IS ASSIGNED, NEVER PICKED. There is no colour picker anywhere in the product, and the domain deals
 * steps in an order that keeps the first four far apart in hue. Nothing here names an ink: a step is an index, and
 * which colour that index renders as belongs to the token layer alone. */

/** The sealed ramp, in the order the tokens name its steps. */
export const AREA_PIGMENTS = [
  "01",
  "02",
  "03",
  "04",
  "05",
  "06",
  "07",
  "08",
  "09",
  "10",
  "11",
  "12",
] as const;

export type AreaPigment = (typeof AREA_PIGMENTS)[number];

/**
 * The ramp step an Area's assigned index lands on.
 *
 * The domain stores `pigment_index`, 0 to 11, and assigns it rather than letting a user pick. The ramp is sealed at
 * twelve, so an index past the end wraps: a thirteenth Area repeats a pigment, which is legible, where a colourless
 * chip would read as a rendering fault.
 */
export function areaPigment(pigmentIndex: number): AreaPigment {
  const steps = AREA_PIGMENTS.length;
  return AREA_PIGMENTS[((Math.trunc(pigmentIndex) % steps) + steps) % steps];
}
