/* The readers a hosted mark's contrast case rests on, including what each REFUSES.
 *
 * The refusals are the point. A reader that returned a guess for a fill it could not resolve would let a case
 * pass on a made-up figure, and a reader that returned the page's ink for a host that sets none would report a
 * ratio nobody can see. Both are asserted here against sheets written for the purpose, so the real sheets'
 * cases are about the kit rather than about the reader. */

import { describe, expect, it } from "vitest";

import { inkRules, surfacesUnder, tokenIn } from "./hostedInk";

const HOST = `
  .control {
    background: var(--ink);
    color: var(--on-ink);
    --mark-ink: var(--on-ink);
  }

  .control--bare {
    background: transparent;
    color: var(--ink);
    --mark-ink: var(--ink);
  }

  .control--sm {
    height: 22px;
  }

  .control--unstated {
    color: var(--ink-deep);
  }

  .control--silent {
    background-color: var(--paper-raised);
    color: var(--ink-deep);
  }
`;

describe("the rules a host writes ink in", () => {
  it("finds every one of them and no rule that writes none", () => {
    expect(inkRules(HOST, "--mark-ink").map((rule) => rule.selector)).toEqual([
      ".control",
      ".control--bare",
      ".control--unstated",
      ".control--silent",
    ]);
  });

  it("reads the ink, the mark's ink and the fill each rule declares", () => {
    const [ink] = inkRules(HOST, "--mark-ink");

    expect(ink).toEqual({
      selector: ".control",
      ink: "var(--on-ink)",
      markInk: "var(--on-ink)",
      fill: "var(--ink)",
    });
  });

  it("reports a rule that hands a mark nothing, rather than filling in the page's ink for it", () => {
    const unstated = inkRules(HOST, "--mark-ink").find(
      (rule) => rule.selector === ".control--unstated",
    );

    expect(unstated?.markInk).toBeNull();
    expect(unstated?.fill).toBeNull();
  });

  it("reads a fill written as background-color, which is the same channel under another name", () => {
    const silent = inkRules(HOST, "--mark-ink").find(
      (rule) => rule.selector === ".control--silent",
    );

    expect(silent?.fill).toBe("var(--paper-raised)");
  });
});

describe("the token a value names", () => {
  it("is the one it references", () => {
    expect(tokenIn("var(--on-ink)")).toBe("--on-ink");
  });

  it("refuses a value that names none, because a ratio needs a token", () => {
    expect(() => tokenIn("#0d1f5c")).toThrow(/names no single token/);
    expect(() => tokenIn(undefined)).toThrow(/nothing names no single token/);
  });

  /* A fallback is refused rather than followed: two tokens are two ratios, and which one a reader sees depends
   * on a cascade this reader cannot see. The mark's own sheet therefore names one token and no fallback. */
  it("refuses a fallback, because which of the two draws is not a fact about this sheet", () => {
    expect(() => tokenIn("var(--mark-ink, var(--ink-deep))")).toThrow(/names no single token/);
  });
});

describe("the surfaces a fill puts under a mark", () => {
  it("is the fill's own token where it has one", () => {
    expect(surfacesUnder("var(--ink)")).toEqual(["--ink"]);
  });

  it("is both papers where the fill is translucent, because either can show through", () => {
    expect(surfacesUnder("transparent")).toEqual(["--paper", "--paper-raised"]);
  });

  it("refuses a rule that declares no fill rather than assuming one", () => {
    expect(() => surfacesUnder(null)).toThrow(/declares no fill/);
  });

  it("refuses a fill no ratio describes, rather than computing one against a texture", () => {
    expect(() => surfacesUnder("var(--hatch-fwd) repeat")).toThrow(/names no single token/);
  });
});
