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

/**
 * A rect that offers the surface `heightPx` pixels of viewport: its top sits that far above the bottom.
 *
 * The week grid's hook measures the space the display still offers it, from `getBoundingClientRect().top`
 * against `window.innerHeight`. A rect is a record here rather than an instance mock, because the hook reads
 * it through the ref before any instance exists to mock one on.
 */
export function offeredRect(heightPx: number): DOMRect {
  /* Not clamped at zero: a display taller than jsdom's own viewport is exactly the case the tall-display tests
   * describe, so the top simply sits above the viewport's top when the offer exceeds it. */
  const top = window.innerHeight - heightPx;
  return {
    top,
    bottom: window.innerHeight,
    height: heightPx,
    left: 0,
    right: 0,
    width: 0,
    x: 0,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

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
