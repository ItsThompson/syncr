/* WHAT COUNTS AS A COPY OF THE WORDS, which is the reading the naming cases rest on.
 *
 * Every case that asserts a group is named once is asserting what this file's two readers report, so a reader
 * blind to half of what it claims to read would make that whole family green by construction: a census that
 * ignored `aria-label` reports one copy for the shape with two, and a dangling-label scan that resolved every
 * target reports nothing for the row that points at nothing.
 *
 * So both readers are given the shape they are meant to find AND the shape they are meant to pass. */

import { afterEach, describe, expect, it } from "vitest";

import { authoredNames, danglingLabels } from "./accessibleNames";

/* A `for` resolves against the DOCUMENT, so a container has to be in one for a resolvable target to resolve.
 * Each is removed again, so one case's ids cannot answer another's. */
const attached: HTMLElement[] = [];

function markup(html: string): HTMLElement {
  const container = document.createElement("div");
  container.innerHTML = html;
  document.body.append(container);
  attached.push(container);
  return container;
}

afterEach(() => {
  for (const container of attached.splice(0)) container.remove();
});

describe("where the words are authored", () => {
  it("finds the element that draws them", () => {
    const container = markup(`<span class="form-row__label">Day bounds</span>`);

    expect(authoredNames(container, "Day bounds")).toEqual([
      { source: "drawn text", by: "span.form-row__label" },
    ]);
  });

  it("finds a control carrying them as its own name, which is the second copy", () => {
    const container = markup(`<p>Day bounds</p><fieldset aria-label="Day bounds"></fieldset>`);

    expect(authoredNames(container, "Day bounds")).toEqual([
      { source: "drawn text", by: "p" },
      { source: "aria-label", by: "fieldset" },
    ]);
  });

  /* A reference is not a copy, which is the whole distinction: Chrome reports this shape's name as coming
   * from a related element rather than from an attribute of the group's own. */
  it("does not count a group pointed at the drawn element", () => {
    const container = markup(
      `<span id="q">Day bounds</span><fieldset aria-labelledby="q"></fieldset>`,
    );

    expect(authoredNames(container, "Day bounds")).toEqual([{ source: "drawn text", by: "span" }]);
  });

  /* An ancestor's text is its descendants' text, so a reader that counted ancestors would report one drawn
   * copy per level of the tree and no row could ever be named once. */
  it("does not count an ancestor whose only text is its child's", () => {
    const container = markup(`<div class="form-row"><span>Day bounds</span></div>`);

    expect(authoredNames(container, "Day bounds")).toEqual([{ source: "drawn text", by: "span" }]);
  });

  /* THE REQUIRED ROW IS WHY THE RULE IS OWN TEXT RATHER THAN LEAF. Its label element draws the words beside a
   * marker element, so it has an element child and a leaf test skipped it: the census reported no authoring at
   * all for a shape the row itself renders, which is a reader blind to the row it is used on. */
  it("counts an element that draws them beside a marker element", () => {
    const container = markup(
      `<span class="form-row__label">Day bounds<span class="form-row__required"> *</span></span>`,
    );

    expect(authoredNames(container, "Day bounds")).toEqual([
      { source: "drawn text", by: "span.form-row__label" },
    ]);
  });

  it("reports nothing for words the render does not carry", () => {
    const container = markup(`<span>Times</span>`);

    expect(authoredNames(container, "Day bounds")).toEqual([]);
  });
});

describe("a label that names nothing", () => {
  it("is reported by the id it points at", () => {
    const container = markup(`<label for="absent">Day bounds</label><fieldset></fieldset>`);

    expect(danglingLabels(container)).toEqual(["absent"]);
  });

  it("is not reported when the target is there", () => {
    const container = markup(`<label for="present">Estimate</label><input id="present" />`);

    expect(danglingLabels(container)).toEqual([]);
  });
});
