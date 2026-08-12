/* KEEPING THE ELEMENT A READER JUST TOUCHED WHERE THEY LEFT IT.
 *
 * Motion is zero, so a disclosure opens and closes in one frame. That is right, and it creates the one problem an
 * animation would have hidden: everything below the toggled element moves by the panel's whole height instantly,
 * and if the element sits below the fold the reader's viewport is suddenly showing different content than the row
 * they clicked. It is a scroll problem rather than a motion problem:
 * measure the element before the layout changes, measure it after, and take the difference out of the scroll
 * position.
 *
 * THE MEASUREMENT IS THE ELEMENT'S OWN TOP, not the scroll offset, because it is the only figure that is stable
 * across the change: the document's height moves, the scroll position moves with it, and the element's distance
 * from the top of the viewport is what a reader actually perceives as "it stayed put".
 *
 * A LAYOUT EFFECT, NOT AN EFFECT. The second measurement has to happen after the DOM is updated and before the
 * browser paints, or the reader sees the jump this exists to prevent and then sees it corrected.
 *
 * IT IS NOT A SCROLL ANIMATION. `scrollBy` with no behaviour is instant, and the design language's zero motion is
 * why: the correction has to be part of the same frame as the collapse, not a movement after it. */

import { useLayoutEffect, useRef } from "react";

export interface ScrollAnchor {
  /**
   * Remember where this element sits, to be called from the handler that is about to change the layout.
   *
   * The element rather than a ref, because the caller has it: a disclosure's own trigger is the event's
   * `currentTarget`, which is exactly the element the reader touched.
   */
  readonly hold: (element: HTMLElement) => void;
}

/**
 * An anchor that restores the held element's position whenever `openState` changes.
 *
 * The dependency is the caller's own record of what is open, because that is what changes the layout: the effect
 * has to run on the render that opened or closed something, and on no other.
 */
export function useScrollAnchor(openState: string): ScrollAnchor {
  const held = useRef<{ element: HTMLElement; top: number } | null>(null);

  useLayoutEffect(() => {
    const anchor = held.current;
    held.current = null;
    if (anchor === null) return;
    const moved = anchor.element.getBoundingClientRect().top - anchor.top;
    if (moved !== 0) window.scrollBy(0, moved);
  }, [openState]);

  return {
    hold: (element: HTMLElement) => {
      held.current = { element, top: element.getBoundingClientRect().top };
    },
  };
}
