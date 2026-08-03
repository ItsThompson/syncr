/* THE PLATES THIS PRODUCT HAS, AND WHERE THE FILES COME FROM.
 *
 * Illustration is GENERATED, not licensed per asset: `scripts/generate-plate` takes a public-domain source, dithers
 * it in the house style, and writes both the plate and a manifest entry naming the source, its licence and the
 * digest of the bytes it was made from. This table is the application's half of that pairing, and the plate test
 * asserts the two agree in both directions, so a plate cannot reach a screen without its provenance recorded.
 *
 * SUBJECTS ARE HOROLOGICAL AND ASTRONOMICAL INSTRUMENTS. Orreries, sundials, escapement mechanisms, astrolabes,
 * armillary spheres, star charts. Thematically exact for a scheduler, and the constraint is what keeps five plates
 * from becoming a mood board. */

import armillary from "../../../assets/plates/armillary.png";
import astrolabe from "../../../assets/plates/astrolabe.png";

export const PLATES = {
  armillary,
  astrolabe,
} as const;

export type PlateName = keyof typeof PLATES;
