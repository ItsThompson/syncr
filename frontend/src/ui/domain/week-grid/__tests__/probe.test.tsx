/* THE RENDERED-PIXEL GATE'S PROBE, HELD AGAINST THE MARKUP THIS COMPONENT ACTUALLY EMITS.
 *
 * `scripts/check-render` is the only gate in this frontend whose input is a rendered pixel, and it reaches a browser
 * as TEXT: the class list, the data attributes and the inline style are written by hand in `page.ts`. That copy is
 * always one edit away from drifting, and a drifted probe measures a shape the product does not ship, which is worse
 * than no probe at all. Rendering the real `Block` and requiring the probe to contain everything it writes is what
 * holds the two together.
 *
 * It lives here rather than beside the script because it is a claim about what this component renders, and because a
 * script's own suite takes plain TypeScript rather than JSX. */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CASES, geometryOf, probePage } from "../../../../../scripts/check-render/page.ts";
import { Block } from "../Block";
import type { GridBlock } from "../types";

const cases = geometryOf(CASES);
const modal = cases[0];
const page = probePage({ bundleName: "bundle.css", cases });

const BLOCK: GridBlock = {
  id: "b1",
  title: modal.title,
  span: { startMin: 540, endMin: 570 },
  origin: "task",
  pigment: "01",
  areaName: "Career",
  isPinned: false,
};

function realBlock(): HTMLElement {
  const { container } = render(
    <Block
      block={BLOCK}
      placement={{
        topPx: modal.cappedTopPx,
        heightPx: modal.heightPx,
        across: { left: 0, right: 0, indentSteps: 0, layer: 0, overlapCount: null, isSplit: false },
      }}
    />,
  );
  const element = container.firstElementChild;
  if (!(element instanceof HTMLElement)) throw new Error("the block rendered nothing");
  return element;
}

describe("the probe's block against this component's", () => {
  it("writes every class the component writes", () => {
    for (const className of realBlock().className.split(/\s+/)) {
      expect(page, `the probe is missing ${className}`).toContain(className);
    }
  });

  it("writes every nested element the component writes", () => {
    for (const child of realBlock().querySelectorAll("[class]")) {
      expect(page, `the probe is missing ${child.className}`).toContain(child.className);
    }
  });

  it("writes every attribute the component writes", () => {
    for (const name of realBlock().getAttributeNames()) {
      if (name === "style" || name === "aria-label") continue;
      expect(page, `the probe is missing ${name}`).toContain(name);
    }
  });

  it("passes the same two per-block custom values the component passes", () => {
    expect(page).toContain("--lines:");
    expect(page).toContain("var(--grid-inset)");
  });

  it("renders the same block height, so the line count under test is the product's", () => {
    expect(realBlock().style.height).toBe(`${modal.heightPx.toFixed(3)}px`);
    expect(page).toContain(`height:${modal.heightPx.toFixed(3)}px`);
  });
});
