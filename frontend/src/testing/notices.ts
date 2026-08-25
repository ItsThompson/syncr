/* Reading the notice surfaces a rendered screen is showing.
 *
 * The class is the kit's own vocabulary -- `surface.ts` maps volume and pigment onto `notice--<kind>` in one
 * place -- so a test that asks "which notices of this kind are on screen" asks through it, rather than through
 * each suite re-assembling the selector. */

/** Every notice surface of one pigment currently rendered, whatever its volume. */
export function noticeSurfaces(container: ParentNode, pigment: string): Element[] {
  return [...container.querySelectorAll(`.notice--${pigment}`)];
}
