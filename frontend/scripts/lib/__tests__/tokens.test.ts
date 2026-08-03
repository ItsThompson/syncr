/* THE TOKEN LAYER READ AS VALUES, which two very different consumers depend on.
 *
 * The contrast ledgers need what a semantic token resolves to in order to compute a ratio from the pigments that
 * ship. The plate generator needs it because a plate is baked bytes: its ink cannot be a `var()` at render time, so
 * the hex is resolved once and written into the file. One reader, so a plate and a ledger cannot disagree about what
 * --ink-deep is, and a token that stops resolving to a colour is a refusal rather than a plate in the wrong ink. */

import { describe, expect, it } from "vitest";

import { declaredTokens, resolveColourToken, resolveToken } from "../tokens.ts";

describe("a semantic token", () => {
  it("resolves through however many var() hops it takes to reach a literal", async () => {
    const tokens = await declaredTokens();

    // --ink-deep is var(--cobalt-700), which is a hex in layer 0.
    expect(resolveToken(tokens, "--ink-deep")).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(resolveToken(tokens, "--paper-raised")).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it("resolves a layer 0 step to itself, since a ramp step IS the literal", async () => {
    const tokens = await declaredTokens();

    expect(resolveToken(tokens, "--pigment-area-07")).toBe("#13746E");
  });

  it("refuses a name the layer does not declare, rather than returning nothing", async () => {
    const tokens = await declaredTokens();

    expect(() => resolveToken(tokens, "--nowhere")).toThrow(/does not resolve/);
  });
});

describe("the ink a plate is baked in", () => {
  it("is the hex --ink-deep resolves to, lowercased for the file it is written into", async () => {
    expect(await resolveColourToken("--ink-deep")).toMatch(/^#[0-9a-f]{6}$/);
  });

  /* A plate cannot be baked in a length or a gradient, and finding that out from a plate that came out wrong is
   * the failure this refusal replaces. */
  it("refuses a token that is not a colour, by name", async () => {
    await expect(resolveColourToken("--h-row")).rejects.toThrow(/not a six-digit hex/);
  });
});
