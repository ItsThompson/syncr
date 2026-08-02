/* The closed vocabulary has ONE definition, and it is the declarations rather than the prose. */

import { describe, expect, it } from "vitest";

import { parseCustomVariants, vocabularyOf } from "../custom-variants.ts";

const DECLARED = [
  "@custom-variant pinned      (&[data-pinned]);",
  '@custom-variant frame       (&[data-origin="frame"]);',
  "@custom-variant dragging    ([data-dragging] &);",
  "@custom-variant hocus       (&:hover, &:focus-visible);",
].join("\n");

describe("parseCustomVariants", () => {
  it("reads the variant name and the attribute its selector keys on", () => {
    expect(parseCustomVariants(DECLARED)).toEqual([
      { name: "pinned", selector: "&[data-pinned]", attribute: "data-pinned" },
      { name: "frame", selector: '&[data-origin="frame"]', attribute: "data-origin" },
      { name: "dragging", selector: "[data-dragging] &", attribute: "data-dragging" },
      { name: "hocus", selector: "&:hover, &:focus-visible" },
    ]);
  });

  it("ignores a declaration inside a block comment", () => {
    const source = `/* @custom-variant busy (&[data-busy]); */\n@custom-variant pinned (&[data-pinned]);`;

    expect(parseCustomVariants(source).map((variant) => variant.name)).toEqual(["pinned"]);
  });
});

describe("vocabularyOf", () => {
  it("is the set of attributes the theme declares a variant for", () => {
    expect([...vocabularyOf(DECLARED)].toSorted()).toEqual([
      "data-dragging",
      "data-origin",
      "data-pinned",
    ]);
  });

  it("does NOT widen for a data attribute named only in a comment", () => {
    const source = "/* one day, maybe data-busy */\n@custom-variant pinned (&[data-pinned]);";

    expect([...vocabularyOf(source)]).toEqual(["data-pinned"]);
  });

  it("does not widen for a data attribute merely used in a selector elsewhere", () => {
    const source = "@custom-variant pinned (&[data-pinned]);\n.row[data-busy] { color: red }";

    expect([...vocabularyOf(source)]).toEqual(["data-pinned"]);
  });
});
