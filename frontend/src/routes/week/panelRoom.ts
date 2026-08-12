/* WHETHER THE DETAIL PANEL HAS ROOM FOR ITS OWN COLUMN, which is the one width question this screen answers in
 * TypeScript rather than in a stylesheet.
 *
 * The threshold is the width policy's own: at --bp-wide seven day columns still hold seventeen characters with the
 * panel open, and below it the panel closes to a rail rather than narrowing. Every utility fenced to that threshold
 * compiles from the theme's mirror of the token, and a compiled media query cannot be read back out of CSS, so the
 * number is mirrored here as well. `__tests__/panelRoom.test.ts` crosses this mirror against what the `wide:` variant
 * compiles to, which is the fence the panel's column actually takes.
 *
 * THE VIEWPORT IS READ FROM `window.innerWidth` RATHER THAN FROM A MEDIA QUERY MATCH, because jsdom implements no
 * `matchMedia` at all: a screen that called it would throw wherever it is rendered outside a browser, and a stub
 * would answer for the stub rather than for the viewport. `innerWidth` is the same number in both places. */

/** The mirror of --bp-wide, which is where the panel's reserved column fits beside seven legible day columns. */
export const WIDE_MIN_WIDTH_PX = 1536;

/** True where the viewport holds the panel's own column, which is where the panel opens without being asked. */
export function hasRoomForDetailPanel(): boolean {
  return window.innerWidth >= WIDE_MIN_WIDTH_PX;
}
