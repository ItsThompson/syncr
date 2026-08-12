/* THE SCROLL ANCHOR, DRIVEN OVER A SIMULATED VIEWPORT.
 *
 * What the hook promises is a reading a reader takes: the row they touched is still the same distance down the
 * screen after the layout changed under it. jsdom has neither layout nor scrolling, so the two figures a browser
 * supplies are supplied here -- how far the row sits down the DOCUMENT, and a scroll position `window.scrollBy`
 * moves -- and the viewport top a reader perceives is the difference. Every case states that difference before
 * the change and asserts it after.
 *
 * THE READING IS THE ASSERTION, NOT THE CALL. A correction of the right size in the wrong direction calls
 * `scrollBy` once with a plausible figure and leaves the page somewhere else, so a case that reads the call
 * cannot tell the fix from that defect. The call count is asserted for one thing only: refusing to scroll by
 * zero is a decision the position cannot see, because a zero-length scroll moves nothing either way. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useScrollAnchor } from "./useScrollAnchor";

/** A row a reader can touch, holding itself the way a disclosure's own trigger does. */
function Row({ openState }: { openState: string }) {
  const anchor = useScrollAnchor(openState);

  return (
    <button
      type="button"
      onClick={(event) => {
        anchor.hold(event.currentTarget);
      }}
    >
      Concrete entries
    </button>
  );
}

/**
 * A page the case moves: how far the row sits down the document, and how far the document is scrolled.
 *
 * Both are one figure to the hook, which only ever reads their difference, and they are separate here because
 * the defect this exists to prevent is the page chasing the row: the document moves, and what must not move is
 * the reader's view of it.
 */
function pageAt(documentTop: number, scrollY: number) {
  const page = { documentTop, scrollY };

  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(
    () => new DOMRect(0, page.documentTop - page.scrollY, 100, 26),
  );
  const scrolled = vi
    .spyOn(window, "scrollBy")
    .mockImplementation((_x?: number | ScrollToOptions, y?: number) => {
      page.scrollY += typeof y === "number" ? y : 0;
    });

  return {
    /** Push the row further down the document, which is what opening a section above it does. */
    rowMovesTo: (nextDocumentTop: number) => {
      page.documentTop = nextDocumentTop;
    },
    /** What the reader sees: the row's distance from the top of the viewport. */
    viewportTop: () => page.documentTop - page.scrollY,
    scrollPosition: () => page.scrollY,
    corrections: () => scrolled.mock.calls.length,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useScrollAnchor", () => {
  it("restores the held row's viewport top when the layout moves the row down", async () => {
    const page = pageAt(300, 200);
    const { rerender } = render(<Row openState="" />);

    await userEvent.click(screen.getByRole("button"));
    page.rowMovesTo(480);
    rerender(<Row openState="concrete" />);

    expect(page.viewportTop()).toBe(100);
    expect(page.scrollPosition()).toBe(380);
    expect(page.corrections()).toBe(1);
  });

  it("leaves the page where it is when the held row did not move", async () => {
    const page = pageAt(300, 200);
    const { rerender } = render(<Row openState="" />);

    await userEvent.click(screen.getByRole("button"));
    rerender(<Row openState="concrete" />);

    expect(page.viewportTop()).toBe(100);
    expect(page.scrollPosition()).toBe(200);
    expect(page.corrections()).toBe(0);
  });

  /* The case above cannot tell a correct refusal from an anchor that never ran, so the run is what this one
   * measures: the hold is spent by the layout change it was taken for, whether or not that change moved
   * anything. An anchor that had not run would still be holding the row here and would chase it. */
  it("spends the hold on the change it was taken for, so a later change is not chased", async () => {
    const page = pageAt(300, 200);
    const { rerender } = render(<Row openState="" />);

    await userEvent.click(screen.getByRole("button"));
    rerender(<Row openState="concrete" />);
    page.rowMovesTo(480);
    rerender(<Row openState="anchors" />);

    expect(page.viewportTop()).toBe(280);
    expect(page.scrollPosition()).toBe(200);
    expect(page.corrections()).toBe(0);
  });

  /* A screen opening a section itself, from a URL or a chord: nothing was held, so nothing is restored.
   * Correcting the scroll here would move the page under a reader who never touched it. */
  it("does not move a page whose reader touched nothing", () => {
    const page = pageAt(300, 200);
    const { rerender } = render(<Row openState="" />);

    page.rowMovesTo(480);
    rerender(<Row openState="concrete" />);

    expect(page.viewportTop()).toBe(280);
    expect(page.scrollPosition()).toBe(200);
    expect(page.corrections()).toBe(0);
  });
});
