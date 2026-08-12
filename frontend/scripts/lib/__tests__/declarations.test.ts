/* The one list of refused declarations, and the conversion that made it reach a TSX object.
 *
 * `cssPropertyFor` is the whole of the mechanism: the inline-style rule enumerated CSS spellings
 * while React writes camelCase, so `backdropFilter`, `willChange`, `WebkitFilter` and `outline: "none"`
 * passed every check and rendered a blur on a kit element. Converting the key is what makes one list
 * serve both inputs, so these cases are the ones the rule's correctness rests on.
 *
 * stylelint imports `BANNED_PROPERTIES` from the same module, so there is nothing to pin equal: the
 * list has one definition and three readers. */

import { describe, expect, it } from "vitest";

import { BANNED_PROPERTIES, cssPropertyFor, refusalFor } from "../declarations.ts";

describe("cssPropertyFor", () => {
  it.each([
    ["backdropFilter", "backdrop-filter"],
    ["willChange", "will-change"],
    ["transitionDelay", "transition-delay"],
    ["borderRadius", "border-radius"],
    ["outline", "outline"],
    ["WebkitFilter", "-webkit-filter"],
    ["WebkitBackdropFilter", "-webkit-backdrop-filter"],
    ["MozOsxFontSmoothing", "-moz-osx-font-smoothing"],
    ["msFilter", "-ms-filter"],
    ["--ai", "--ai"],
  ])("converts %s to %s", (styleKey, property) => {
    expect(cssPropertyFor(styleKey)).toBe(property);
  });
});

describe("refusalFor", () => {
  it("refuses every React spelling of a filter, which is what escaped the old rule", () => {
    for (const key of ["backdropFilter", "WebkitFilter", "filter"]) {
      expect(refusalFor(cssPropertyFor(key), "blur(4px)")).not.toBeNull();
    }
  });

  it("permits the ring the base layer draws, so the shared list cannot outlaw the design", () => {
    expect(refusalFor("outline", "var(--state-focus-ring)")).toBeNull();
  });

  it("refuses removing the ring, whatever the spelling of nothing", () => {
    expect(refusalFor("outline", "none")).not.toBeNull();
    expect(refusalFor("outline", "0")).not.toBeNull();
  });

  it("permits animation: none, which is the one legal motion value", () => {
    expect(refusalFor("animation", "none")).toBeNull();
    expect(refusalFor("animation", "spin 1s")).not.toBeNull();
  });

  it("ignores whitespace and case, so a formatter cannot change a verdict", () => {
    expect(refusalFor(" WILL-CHANGE ", "  transform  ")).not.toBeNull();
    expect(refusalFor("box-shadow", "  var(--shadow-hard)  ")).toBeNull();
  });
});

/* THE LIST'S OWN SHAPE. stylelint, the emitted verdict, the inline-style rule and the bundle gate all
 * read this one set, so an empty or truncated set would silently disable four checks at once. */
describe("the banned property list", () => {
  it("holds every motion property the design language names, so no reader is enforcing nothing", () => {
    for (const property of [
      "transition",
      "transition-behavior",
      "animation",
      "transform",
      "translate",
      "rotate",
      "scale",
      "will-change",
    ]) {
      expect(BANNED_PROPERTIES.has(property)).toBe(true);
    }
  });
});
