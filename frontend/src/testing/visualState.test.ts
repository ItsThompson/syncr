/* The helper that decides what a kit element looks like, checked against known input.
 *
 * A script that measures whether a check works needs its own result checked against something independently
 * known: this repository has produced five measurement-tooling bugs, every one of them in code whose only job
 * was verifying something else. `visualState` is exactly that kind of code, and the combination matrix's whole
 * verdict rests on it, so these cases are stylesheets small enough to reason about by eye. */

import { describe, expect, it } from "vitest";

import { appliedDeclarations, effectiveDeclarations, signatureOf } from "./visualState";

function element(html: string): Element {
  const host = document.createElement("div");
  host.innerHTML = html;
  const first = host.firstElementChild;
  if (first === null) throw new Error("no element in the fixture");
  return first;
}

describe("appliedDeclarations", () => {
  it("collects the declarations of a rule that matches", () => {
    const applied = appliedDeclarations({
      element: element(`<div class="row"></div>`),
      css: ".row { color: var(--ink); background: var(--paper); }",
    });

    expect(applied).toEqual(["color: var(--ink)", "background: var(--paper)"]);
  });

  it("ignores a rule that does not match", () => {
    const applied = appliedDeclarations({
      element: element(`<div class="row"></div>`),
      css: ".other { color: var(--ink); }",
    });

    expect(applied).toEqual([]);
  });

  it("matches on an attribute, which is how every state in this kit is written", () => {
    const applied = appliedDeclarations({
      element: element(`<div class="row" data-current=""></div>`),
      css: ".row[data-current] { border-left-color: var(--ink-deep); }",
    });

    expect(applied).toEqual(["border-left-color: var(--ink-deep)"]);
  });

  /* jsdom's `matches(":hover")` is always false, because nothing hovers in a headless DOM. A pseudo-class named
   * as active is removed from the selector before matching, which is what the browser does when the state is on. */
  it("treats a named pseudo-class as active, since jsdom can never match one", () => {
    const input = {
      element: element(`<div class="row"></div>`),
      css: ".row:hover { background-color: var(--state-hover); }",
    };

    expect(appliedDeclarations(input)).toEqual([]);
    expect(appliedDeclarations({ ...input, active: [":hover"] })).toEqual([
      "background-color: var(--state-hover)",
    ]);
  });

  it("does not confuse a pseudo-element's declarations with the element's own", () => {
    const applied = appliedDeclarations({
      element: element(`<span class="glyph"></span>`),
      css: ".glyph::before { content: var(--glyph); }",
    });

    expect(applied).toEqual(["::before content: var(--glyph)"]);
  });

  it("reads a rule with several selectors when any one of them matches", () => {
    const applied = appliedDeclarations({
      element: element(`<button class="box" disabled></button>`),
      css: ".box:disabled, .box[aria-disabled='true'] { border-style: dashed; }",
    });

    expect(applied).toEqual(["border-style: dashed"]);
  });

  it("counts a rule once even when two of its selectors match", () => {
    const applied = appliedDeclarations({
      element: element(`<div class="row" data-current=""></div>`),
      css: ".row, .row[data-current] { color: var(--ink-deep); }",
    });

    expect(applied).toEqual(["color: var(--ink-deep)"]);
  });

  it("survives a selector jsdom cannot parse rather than failing the test that used it", () => {
    const applied = appliedDeclarations({
      element: element(`<div class="row"></div>`),
      css: ".row::-webkit-calendar-picker-indicator { display: none; } .row { color: var(--ink); }",
    });

    expect(applied).toEqual(["color: var(--ink)"]);
  });
});

describe("effectiveDeclarations", () => {
  it("lets the later declaration of a property win, which is the cascade at equal specificity", () => {
    const effective = effectiveDeclarations({
      element: element(`<div class="row" data-current=""></div>`),
      css: ".row { background-color: transparent; } .row[data-current] { background-color: var(--state-hover); }",
    });

    expect(effective.get("background-color")).toBe("var(--state-hover)");
    expect(effective.size).toBe(1);
  });

  it("keeps two different properties apart", () => {
    const effective = effectiveDeclarations({
      element: element(`<div class="row"></div>`),
      css: ".row { color: var(--ink); border-left-color: transparent; }",
    });

    expect([...effective.keys()].toSorted()).toEqual(["border-left-color", "color"]);
  });
});

describe("signatureOf", () => {
  it("is equal for two elements that resolve to the same declarations", () => {
    const css = ".row { color: var(--ink); } .row[data-current] { color: var(--ink); }";

    expect(signatureOf({ element: element(`<div class="row"></div>`), css })).toBe(
      signatureOf({ element: element(`<div class="row" data-current=""></div>`), css }),
    );
  });

  it("differs where one element takes a declaration the other does not", () => {
    const css =
      ".row { color: var(--ink); } .row[data-current] { border-left-color: var(--ink-deep); }";

    expect(signatureOf({ element: element(`<div class="row"></div>`), css })).not.toBe(
      signatureOf({ element: element(`<div class="row" data-current=""></div>`), css }),
    );
  });

  it("does not depend on the order the declarations were written in", () => {
    const one = ".row { color: var(--ink); background: var(--paper); }";
    const other = ".row { background: var(--paper); color: var(--ink); }";

    expect(signatureOf({ element: element(`<div class="row"></div>`), css: one })).toBe(
      signatureOf({ element: element(`<div class="row"></div>`), css: other }),
    );
  });
});
