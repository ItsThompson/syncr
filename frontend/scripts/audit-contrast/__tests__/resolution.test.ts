/* THE RESOLUTION WALK, AGAINST TOKEN GRAPHS SMALL ENOUGH TO REASON ABOUT BY EYE.
 *
 * `coloursOf` decides what the ledger measures, and until now nothing tested it directly: the gate's cases drive
 * synthesised ledgers, so the walk that BUILDS one was covered only by the figures it happened to produce. This
 * repository has produced five measurement-tooling bugs, every one in code whose only job was verifying something
 * else, and a resolver that silently dropped a carrier would shrink the matrix without failing anything.
 *
 * The three behaviours worth pinning are the three the real palette needs: a chain resolves to the NAME a reader
 * would edit rather than to the ramp step under it, a CARRIER resolves to the several names it can hold, and a
 * value that is not a colour is reported with the reason rather than measured or dropped. */

import { describe, expect, it } from "vitest";

import { coloursOf, hexOf, tokensIn, whyUnmeasurable } from "../resolution.ts";

/** A token graph as the scan builds one: a name to every value the tree assigns it. */
function held(graph: Readonly<Record<string, readonly string[]>>): Map<string, Set<string>> {
  return new Map(Object.entries(graph).map(([name, values]) => [name, new Set(values)]));
}

describe("a token that resolves to one colour", () => {
  it("is reported as itself, because the name a component wrote is the name a reader would edit", () => {
    const graph = held({ "--ink": ["var(--cobalt-600)"], "--cobalt-600": ["#16307f"] });

    expect([...coloursOf(graph, "--ink").tokens]).toEqual(["--ink"]);
  });

  it("resolves through as many hops as the layer takes", () => {
    const graph = held({
      "--text": ["var(--ink)"],
      "--ink": ["var(--cobalt-600)"],
      "--cobalt-600": ["#16307f"],
    });

    expect([...coloursOf(graph, "--text").tokens]).toEqual(["--text"]);
    expect(hexOf(graph, "--text")).toBe("#16307f");
  });

  it("is reported as itself when it holds a hex directly, which is layer 0", () => {
    expect([...coloursOf(held({ "--cobalt-600": ["#16307f"] }), "--cobalt-600").tokens]).toEqual([
      "--cobalt-600",
    ]);
  });
});

describe("a carrier", () => {
  /* `--ai` is the Area identity and the class on the element decides which pigment it holds. Following it is what
   * makes the twelve measurable as the indicators they are; reporting `--ai` alone would measure nothing. */
  it("resolves to every name it can hold", () => {
    const graph = held({
      "--ai": ["var(--area-01)", "var(--area-02)"],
      "--area-01": ["#ab4757"],
      "--area-02": ["#a3511e"],
    });

    expect([...coloursOf(graph, "--ai").tokens].toSorted()).toEqual(["--area-01", "--area-02"]);
  });

  it("stops at a cycle rather than walking it, so a mistyped layer cannot hang the ledger", () => {
    const graph = held({ "--a": ["var(--b)"], "--b": ["var(--a)"] });

    expect([...coloursOf(graph, "--a").tokens]).toEqual([]);
  });
});

describe("a value no ratio can describe", () => {
  it.each([
    ["currentColor", "inherits"],
    ["repeating-linear-gradient(45deg, red 0 1px, transparent 1px 5px)", "texture"],
    ["color-mix(in srgb, var(--ink-deep) 30%, transparent)", "transparency"],
    ["45%", "percentage"],
  ])("names why %s is not one", (value, expected) => {
    const reason = whyUnmeasurable(value);

    expect(reason).not.toBeNull();
    expect(reason ?? "").toContain(expected);
  });

  it("is reported under the token a reader would edit, with the reason, and measured as nothing", () => {
    const graph = held({ "--hatch-ink": ["currentColor"] });
    const resolved = coloursOf(graph, "--hatch-ink");

    expect([...resolved.tokens]).toEqual([]);
    expect(resolved.unmeasurable.map((one) => one.token)).toEqual(["--hatch-ink"]);
    expect(resolved.unmeasurable[0].reason).toContain("inherits");
  });

  /* A chain through an unmeasurable value reports the name the SHEET wrote rather than the one it resolved to, so a
   * finding points at the declaration a reader would open. */
  it("is renamed to the token that reached it", () => {
    const graph = held({
      "--forbidden-hatch-ink": ["var(--hatch-ink)"],
      "--hatch-ink": ["currentColor"],
    });

    expect(coloursOf(graph, "--forbidden-hatch-ink").unmeasurable.map((one) => one.token)).toEqual([
      "--forbidden-hatch-ink",
    ]);
  });

  it("leaves a real colour measurable, so the classification is not refusing everything", () => {
    expect(whyUnmeasurable("#16307f")).toBeNull();
  });
});

describe("the reference reader", () => {
  it("finds every token a composed value names", () => {
    expect(tokensIn("color-mix(in srgb, var(--ai) var(--hatch-mix), var(--paper-raised))")).toEqual(
      ["--ai", "--hatch-mix", "--paper-raised"],
    );
  });

  it("finds none in a literal", () => {
    expect(tokensIn("#16307f")).toEqual([]);
  });
});

describe("hexOf", () => {
  it("refuses a name that holds no flat colour, rather than inventing one", () => {
    expect(() => hexOf(held({ "--hatch-ink": ["currentColor"] }), "--hatch-ink")).toThrow(
      /holds no flat colour/,
    );
  });

  it("refuses a name the graph does not know", () => {
    expect(() => hexOf(held({}), "--absent")).toThrow(/holds no flat colour/);
  });
});
