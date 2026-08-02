/* Fixture: one half of an import cycle. A graph walk without a visited set spins here forever, so
 * this exists to prove termination rather than to prove a violation. */

export { fromB } from "./loop-b.ts";

export const fromA = "a";
