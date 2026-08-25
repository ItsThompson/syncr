/* THE HEIGHT THE DISPLAY STILL OFFERS THE SURFACE, OBSERVED RATHER THAN READ ONCE.
 *
 * Pixels per minute is derived from the space the viewport has left for the grid, which is what makes
 * the axis fit the display it is on rather than an assumed one: a 790px viewport less the page band, the
 * summary strip and everything else above the surface.
 *
 * WHY THIS IS NOT THE ELEMENT'S OWN HEIGHT. The measurement sizes the canvases inside the element it
 * reads, so a height read off the element itself feeds back into itself: each round draws a taller canvas,
 * the element grows to hold it, and the next round measures the growth. Measured, that loop runs to the
 * browser's ceiling on element height and the week becomes a 33-million-pixel page. What the arithmetic
 * wants is the space OFFERED to the surface, and that figure does not depend on what the surface drew:
 * it is the distance from the surface's top, in document coordinates, to the bottom of the viewport.
 *
 * DOCUMENT COORDINATES, not `getBoundingClientRect().top` alone: rect top moves with scroll, so a reader
 * scrolled partway down the week would measure a different grid than one at the top. Adding scroll back
 * makes the figure a fact about the layout, identical whichever way a later resize finds the page scrolled.
 *
 * Zero until an element is attached and laid out, which is what a first paint and a headless DOM both
 * report. The caller decides what to do with a zero rather than this hook guessing, so the fallback is
 * stated once, in the geometry that needs it.
 *
 * A `ResizeObserver` ON THE BODY, because the offered space changes for reasons no single element reports:
 * a notice appearing above pushes the surface down, the detail panel changes its width, and the window
 * itself resizes. Every one of those changes the body's box. Observing the body cannot feed back, because
 * the body growing when this surface draws a taller canvas leaves the offered distance unchanged. */

import { useLayoutEffect, useState, type RefObject } from "react";

export function useOfferedHeight(target: RefObject<HTMLElement | null>): number {
  const [heightPx, setHeightPx] = useState(0);

  useLayoutEffect(() => {
    const element = target.current;
    if (element === null) return undefined;

    const measure = (): void => {
      const box = element.getBoundingClientRect();
      if (box.height === 0) return;
      setHeightPx(Math.max(window.innerHeight - (box.top + window.scrollY), 0));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(document.body);
    measure();
    return () => {
      observer.disconnect();
    };
  }, [target]);

  return heightPx;
}
