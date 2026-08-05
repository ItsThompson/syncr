/* THE ELEMENT'S OWN HEIGHT, OBSERVED RATHER THAN READ ONCE.
 *
 * Pixels per minute is derived from the grid's MEASURED height, which is the whole reason the axis fits the
 * viewport it is in rather than an assumed one. A single read at mount would leave the axis proportional to a
 * height that no longer exists the moment the window resizes or the detail panel closes to its rail, and both of
 * those change the grid's height without changing anything it renders from.
 *
 * A `ResizeObserver` rather than a window listener, because the grid's height changes for reasons the window
 * never hears about: the summary strip is fixed, the page band is fixed, and what is left is the grid's.
 *
 * Zero until an element is attached and laid out, which is what a first paint and a headless DOM both report. The
 * caller decides what to do with a zero rather than this hook guessing, so the fallback is stated once, in the
 * geometry that needs it. */

import { useLayoutEffect, useState, type RefObject } from "react";

export function useObservedHeight(target: RefObject<HTMLElement | null>): number {
  const [heightPx, setHeightPx] = useState(0);

  useLayoutEffect(() => {
    const element = target.current;
    if (element === null) return undefined;

    const observer = new ResizeObserver(() => {
      setHeightPx(element.clientHeight);
    });
    observer.observe(element);
    setHeightPx(element.clientHeight);
    return () => {
      observer.disconnect();
    };
  }, [target]);

  return heightPx;
}
