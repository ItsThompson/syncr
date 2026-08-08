/* WHAT A LOADING INDICATOR WOULD LOOK LIKE, SO A RENDERED SCREEN CAN BE ASKED WHETHER IT HAS ONE.
 *
 * The kit has no spinner, no skeleton and no progress bar, and `kitExports.test.ts` asserts that over the barrels.
 * That answers what the kit EXPORTS. It does not answer what a screen RENDERS: a route can write
 * `<progress>`, a `role="progressbar"`, an `aria-busy` region or a third-party component's own `div.spinner`
 * without importing anything from the kit at all, and every one of those would be a moving surface in a product
 * whose motion is zero.
 *
 * So the question is asked of the DOM the route produced. The selectors below are the vocabularies something
 * might use rather than the ones this repository uses: a match is a finding, because there is no legitimate
 * loading indicator anywhere in this product. `e2e/tests/s22-no-motion.spec.ts` asks the same question of a real
 * browser, where a computed style is available; this is the jsdom half, and what it has instead is the ability to
 * put a screen into a state a fixture cannot reach in a live stack.
 *
 * `aria-busy` is included because it is the accessible spelling of "this is loading": a screen that renders a
 * static reading and marks it busy has told a screen-reader user to wait for a redraw that is already done. */

/** Anything that would tell a reader, by role, class or ARIA, that something is in motion. */
export const INDICATOR_SELECTORS: readonly string[] = [
  '[role="progressbar"]',
  "progress",
  '[aria-busy="true"]',
  '[class*="spinner" i]',
  '[class*="skeleton" i]',
  '[class*="loader" i]',
  '[class*="animate-" i]',
  '[class*="pulse" i]',
  '[class*="spin" i]',
];

export interface FoundIndicator {
  readonly selector: string;
  /** The element's own class list, so a finding names something a reader can grep for. */
  readonly className: string;
}

/** Every element in a rendered tree that claims something is in motion. Empty is the only passing answer. */
export function indicatorsIn(root: ParentNode): FoundIndicator[] {
  return INDICATOR_SELECTORS.flatMap((selector) =>
    [...root.querySelectorAll(selector)].map((element) => ({
      selector,
      className: element.className.toString(),
    })),
  );
}
