/* THE MEASUREMENT THE GRID DERIVES EVERYTHING FROM.
 *
 * What these cases hold is the hook's own contract, separate from what the grid does with the figure:
 * the value is the viewport space the element is offered, it follows the display and the layout above the
 * surface rather than anything the surface drew, and an element nothing has laid out measures zero so the
 * geometry's fallback decides. */

import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useRef, type ReactElement } from "react";

import { useOfferedHeight } from "../useOfferedHeight";
import { offeredRect } from "../../../../testing/layoutStubs";

/** A real element carrying the ref, since jsdom gives none of its own geometry to observe. */
function mountSurface(): { readonly measures: () => number } {
  let latest = 0;
  function Surface(): ReactElement {
    const target = useRef<HTMLDivElement>(null);
    latest = useOfferedHeight(target);
    return <div ref={target}>surface</div>;
  }
  render(<Surface />);
  return { measures: () => latest };
}

describe("useOfferedHeight", () => {
  let originalRect: PropertyDescriptor | undefined;
  let rect: DOMRect;
  let notifyObservers: () => void;

  /** A ResizeObserver that records the callback so a test drives a body change the way a browser reports one. */
  const observeBody = (): (() => void) => {
    const installed = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class implements ResizeObserver {
      #callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.#callback = callback;
      }
      observe(): void {
        notifyObservers = () =>
          act(() => {
            this.#callback([], this);
          });
      }
      unobserve(): void {}
      disconnect(): void {}
    };
    return () => {
      globalThis.ResizeObserver = installed;
    };
  };

  beforeEach(() => {
    notifyObservers = () => {};
    rect = offeredRect(500);
    originalRect = Object.getOwnPropertyDescriptor(Element.prototype, "getBoundingClientRect");
    Object.defineProperty(Element.prototype, "getBoundingClientRect", {
      configurable: true,
      value: () => rect,
    });
  });

  afterEach(() => {
    if (originalRect === undefined)
      delete (Element.prototype as { getBoundingClientRect?: unknown }).getBoundingClientRect;
    else Object.defineProperty(Element.prototype, "getBoundingClientRect", originalRect);
  });

  it("measures the viewport space below the element's top", () => {
    const restore = observeBody();
    try {
      const surface = mountSurface();
      expect(surface.measures()).toBe(window.innerHeight - rect.top);
    } finally {
      restore();
    }
  });

  it("re-measures when the layout around the surface changes", () => {
    const restore = observeBody();
    try {
      const surface = mountSurface();
      const before = surface.measures();
      rect = offeredRect(300);
      expect(notifyObservers).toBeDefined();
      notifyObservers();
      expect(surface.measures()).toBe(window.innerHeight - rect.top);
      expect(surface.measures()).not.toBe(before);
    } finally {
      restore();
    }
  });

  it("stays at zero while nothing has laid the element out, which is what the fallback answers", () => {
    const restore = observeBody();
    try {
      rect = { ...(rect as unknown as object), top: 0, bottom: 0, height: 0 } as DOMRect;
      const surface = mountSurface();
      expect(surface.measures()).toBe(0);
      notifyObservers();
      expect(surface.measures()).toBe(0);
    } finally {
      restore();
    }
  });

  it("never offers a negative figure when the surface sits below the viewport's bottom", () => {
    const restore = observeBody();
    try {
      rect = offeredRect(-50);
      const surface = mountSurface();
      expect(surface.measures()).toBe(0);
    } finally {
      restore();
    }
  });
});
