/* The browser APIs jsdom does not implement and the kit's own controls call unconditionally.
 *
 * jsdom is a DOM, not a layout engine, so it has no ResizeObserver and no element geometry. Radix's Select
 * and Popover measure their trigger before they position their content, and its Select captures the pointer
 * to tell a click from a drag. The week grid's drag captures the pointer for a different reason: without
 * capture a release outside the viewport delivers no `pointerup` to the page at all, so the drag never ends.
 * Without these five, opening either control or beginning a drag throws a TypeError and every test about it
 * fails for a reason that has nothing to do with the kit.
 *
 * Each stub is the smallest thing that answers the call. None of them pretends to measure: a test that needs
 * a real position needs a real browser, which is what the E2E suite is for. */

class NoLayoutResizeObserver implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function scrollIntoView(): void {}

function hasPointerCapture(): boolean {
  return false;
}

function releasePointerCapture(): void {}

function setPointerCapture(): void {}

export function installLayoutStubs(): void {
  globalThis.ResizeObserver ??= NoLayoutResizeObserver;
  Element.prototype.scrollIntoView ??= scrollIntoView;
  Element.prototype.hasPointerCapture ??= hasPointerCapture;
  Element.prototype.releasePointerCapture ??= releasePointerCapture;
  Element.prototype.setPointerCapture ??= setPointerCapture;
}
