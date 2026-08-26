/* THE RENDERED-PIXEL GATE'S VERDICT PANEL, HELD AGAINST THE MARKUP THIS COMPONENT ACTUALLY EMITS.
 *
 * `scripts/check-render/verdictPanel.ts` writes the panel's markup by hand, because the page reaches a browser as
 * text. That copy is always one edit away from drifting, and a drifted section measures a panel the product does not
 * ship -- a clipped-edge reading taken off the wrong DOM answers nothing about the product. Rendering the real
 * `VerdictPanel` over the case's own verdict and requiring the section's subtree to equal it is what holds the two
 * together.
 *
 * It lives here rather than beside the script because it is a claim about what this component renders, and because a
 * script's own suite takes plain TypeScript rather than JSX. */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { geometryOf, CASES, probePage } from "../../../../../scripts/check-render/page.ts";
import {
  CASE_VERDICT,
  ROW_COUNT,
  VERDICT_SECTION,
} from "../../../../../scripts/check-render/verdictPanel.ts";
import { VerdictPanel } from "../VerdictPanel";

const page = probePage({ bundleName: "bundle.css", cases: geometryOf(CASES) });

/** One line per element: its tag, its class list, its attribute names and the text it writes itself. */
function shapeOf(root: Element, depth = 0): string[] {
  const text = [...root.childNodes]
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent)
    .join("");
  const attributes = root.getAttributeNames().toSorted().join(" ");
  return [
    `${"  ".repeat(depth)}${root.tagName.toLowerCase()} [${root.className}] [${attributes}] ${JSON.stringify(text)}`,
    ...[...root.children].flatMap((child) => shapeOf(child, depth + 1)),
  ];
}

function sectionPanel(): Element {
  const holder = document.createElement("div");
  holder.innerHTML = VERDICT_SECTION.html;
  const panel = holder.querySelector(".verdict-panel");
  if (panel === null) throw new Error("the section holds no verdict panel");
  return panel;
}

function realPanel(): Element {
  /* The exact inputs the case renders: an infeasible probe verdict enumerating the four offers, no concession, and
   * no controls, which is the variant the gate needs -- a button's ink would sit inside the measured rows. */
  const { container } = render(<VerdictPanel verdict={CASE_VERDICT} />);
  const panel = container.querySelector(".verdict-panel");
  if (panel === null) throw new Error("the component rendered no verdict panel");
  return panel;
}

describe("the probe's verdict panel against this component's", () => {
  it("writes the same tags, classes, attributes and nesting the component writes for the case's verdict", () => {
    expect(shapeOf(sectionPanel())).toEqual(shapeOf(realPanel()));
  });

  it("carries the four tradeoff rows whose clipped edge the gate measures", () => {
    expect(sectionPanel().querySelectorAll(".verdict-panel__row")).toHaveLength(ROW_COUNT);
    expect(realPanel().querySelectorAll(".verdict-panel__row")).toHaveLength(ROW_COUNT);
  });

  it("puts the panel on the page, so the gate reads a section the page actually holds", () => {
    expect(page).toContain(VERDICT_SECTION.html);
  });
});
