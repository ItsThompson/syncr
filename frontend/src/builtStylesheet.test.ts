/* The stylesheet a browser downloads, asserted against the design language's absolutes.
 *
 * This is the same verdict `just lint-frontend` runs as `lint:bundle`, kept as a test as well because
 * the suite is what a developer runs while writing a component, and a banned declaration reaching the
 * artifact is the one defect this repository has shipped to production. It was shipped for three
 * review iterations while every check was green.
 *
 * The three cases below are the three routes by which a name reached the bundle without being a class
 * on a rendered element: a plain string in a test, a `className` in a `__fixtures__` file, and prose in
 * a comment. The first two are closed by the narrowed content scan and are asserted here. The third is
 * NOT closed by the scan, because a comment in an ordinary source file is scanned exactly as its code
 * is; the gate in the first test is what catches it, which is why the gate is not merely the belt to
 * the scan's braces. */

import { describe, expect, it } from "vitest";

import { checkBundle } from "../scripts/check-bundle/check.ts";
import { buildBarrelPayloads, buildStylesheets } from "../scripts/check-bundle/build.ts";

/* ONE build for the file. Vite is invoked with `write: false`, so this leaves no `dist/` behind and
 * cannot read a stale one. The barrel probes are built the same way, and are the figures the gate
 * prints for what importing one component through a barrel loads. */
const built = buildStylesheets();
const barrels = buildBarrelPayloads();

async function builtCss(): Promise<string> {
  return (await built).map((stylesheet) => stylesheet.css).join("\n");
}

/* A candidate named as a plain string, which is neither a class list nor a composer argument, so the
 * markup scan is blind to it by design while Tailwind's extractor reads it. It shipped
 * `will-change: transform` with all seven checks green. */
const NAMED_IN_A_TEST = "will-change-transform";

describe("the built stylesheet", () => {
  it("carries no declaration the design language refuses", async () => {
    const outcome = checkBundle({ stylesheets: await built, barrels: await barrels });

    expect(outcome.findings).toEqual([]);
  });

  it("carries the utilities the application actually writes, so the check is not passing on nothing", async () => {
    const css = await builtCss();

    expect(css).toContain("background-color:var(--paper)");
    expect(css).toContain("width:var(--w-sidebar)");
  });

  /* A component stylesheet nobody imports is invisible to every other test in the suite: the rules would be
   * correct, the tests that read the FILE would pass, and a browser would receive none of it. These are the
   * layer's load-bearing rules, read out of the artifact. */
  it("carries the kit's own stylesheets, so an unimported one cannot pass unnoticed", async () => {
    const css = await builtCss();

    expect(css).toContain(".state-row[data-current]");
    expect(css).toContain(".state-row[data-highlighted]");
    expect(css).toContain("--glyph-check");
    expect(css).toContain(".control");
    expect(css).toContain(".button");
    expect(css).toContain(".overlay");
    expect(css).toContain(".icon");
  });

  it("draws the focus ring and the inverse ring, which no component declares", async () => {
    const css = await builtCss();

    expect(css).toContain("outline:var(--state-focus-ring)");
    expect(css).toContain(".on-ink-surface :focus-visible");
    expect(css).toContain("outline:var(--state-focus-ring-inverse)");
  });

  /* MOTION IS ZERO IN THE ARTIFACT, not only in the files this repository writes. `--duration` is read out of
   * the bundle rather than out of `layout.css`, because what a browser gets is the token layer AFTER the build
   * has processed it, and a token nothing ships is a value nothing is drawn with. The keyframe check is the
   * positive side of the gate the check itself now refuses: a list here would be legal declaration by
   * declaration, and this reads the artifact for the at-rule. */
  it("ships --duration as 0s, so nothing in the product has a length to move over", async () => {
    expect(await builtCss()).toContain("--duration:0s");
  });

  it("ships no keyframe list at all, whatever its frames declare", async () => {
    const css = await builtCss();

    expect(css.toLowerCase()).not.toContain("keyframes");
  });

  it("does not compile a utility named in a test file's string", async () => {
    expect(NAMED_IN_A_TEST).toBe("will-change-transform");
    expect(await builtCss()).not.toContain("will-change");
  });

  it("does not compile a utility named in a fixture's className", async () => {
    const css = await builtCss();

    expect(css).not.toContain("--tw-blur");
    expect(css).not.toContain("--tw-shadow:var(--halo)");
    expect(css).not.toContain("transition-delay");
    expect(css).not.toContain("backdrop-filter");
  });
});
