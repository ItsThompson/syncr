/* The bundle gate's own verdict, over stylesheets that name each shape deliberately.
 *
 * The negative cases matter as much as the positive ones. A regex survey of this very stylesheet
 * reported four violations that were not there: `rotate:` inside `--tw-backdrop-hue-rotate`, `scale:`
 * and `filter:` inside `--tw-backdrop-grayscale` and `--tw-backdrop-blur`, and `transform:` inside
 * `text-transform`. Reading declarations with a real parser is what makes the verdict trustworthy, and
 * the second block below is what keeps it that way. */

import { describe, expect, it } from "vitest";

import { checkBundle } from "../check.ts";
import { BARREL_PROBES } from "../barrels.ts";

function verdictFor(css: string) {
  return checkBundle({
    stylesheets: [{ file: "/dist/assets/probe.css", name: "probe.css", css }],
    barrels: [],
  });
}

function reasons(css: string): string[] {
  return verdictFor(css).findings.map((finding) => finding.message);
}

describe("a declaration the design language refuses", () => {
  it.each([
    [".a{transition-property:color}", "transition-property"],
    [".a{transition-delay:300ms}", "transition-delay"],
    [".a{transition-behavior:allow-discrete}", "transition-behavior"],
    [".a{will-change:transform}", "will-change"],
    [".a{animation:spin 1s linear infinite}", "animation"],
    [".a{rotate:3deg}", "rotate"],
    [".a{scale:1.05}", "scale"],
    [".a{translate:0 2px}", "translate"],
    [".a{transform:rotate(3deg)}", "transform"],
    [".a{filter:blur(4px)}", "filter"],
    [".a{backdrop-filter:blur(4px)}", "backdrop-filter"],
    [".a{-webkit-backdrop-filter:blur(4px)}", "-webkit-backdrop-filter"],
    [".a{-webkit-filter:blur(4px)}", "-webkit-filter"],
    [".a{box-shadow:0 0 8px red}", "box-shadow"],
    [".a{--tw-shadow:var(--halo)}", "--tw-shadow"],
    [".a{outline:none}", "outline"],
    [".a{outline-style:none}", "outline-style"],
    [".a{outline-width:0}", "outline-width"],
  ])("%s is refused, naming %s", (css, property) => {
    const found = reasons(css);

    expect(found).toHaveLength(1);
    expect(found[0]).toContain(property);
  });

  it("names the selector it shipped under, so a reader can find it in the artifact", () => {
    expect(reasons(".backdrop-filter{backdrop-filter:blur(4px)}")[0]).toContain(".backdrop-filter");
  });

  it("names the at-rule when the declaration sits inside one", () => {
    expect(reasons("@media (width >= 1536px){.a{will-change:transform}}")[0]).toContain("@media");
  });

  it("reads a declaration nested two levels deep, which a rule-body scan would miss", () => {
    expect(reasons("@supports (color:red){@media print{.a{filter:blur(1px)}}}")).toHaveLength(1);
  });

  it("abbreviates a composed value rather than printing three hundred characters of it", () => {
    const long = `.a{transition-property:${"color,".repeat(60)}color}`;

    expect(reasons(long)[0]).toContain("...");
  });
});

/* THE FALSE POSITIVES A PATTERN PRODUCES ON THIS EXACT STYLESHEET. Every one of these is in the real
 * built output today, and a check that failed on them would be turned off within a week. */
describe("a declaration the design language permits", () => {
  it.each([
    ".a{--tw-backdrop-hue-rotate:initial}",
    ".a{--tw-backdrop-grayscale:initial}",
    ".a{--tw-backdrop-blur:initial}",
    ".a{text-transform:uppercase}",
    ".a{animation:none}",
    ".a{--tw-shadow:var(--shadow-hard)}",
    ".a{--tw-shadow:0 0 #0000}",
    ".a{box-shadow:var(--tw-inset-shadow), var(--tw-ring-shadow), var(--tw-shadow)}",
    ".a{outline:var(--state-focus-ring)}",
    ".a{outline:auto}",
    ".a{outline-style:solid}",
    ".a{outline-width:2px}",
    ".a{outline-offset:var(--state-focus-offset)}",
    ".a{border-radius:50%}",
    ".a{background-color:var(--paper)}",
  ])("%s produces no finding", (css) => {
    expect(reasons(css)).toEqual([]);
  });
});

/* THE SHAPE A DECLARATION WALK CANNOT SEE, WHICH IS WHY THE AT-RULE IS READ.
 *
 * `@keyframes fade { to { opacity: 1 } }` declares `opacity`, and `opacity` is legal everywhere else in this
 * product. So the frames of an animation are each a permitted declaration and the animation is the violation:
 * a check reading only declarations reports nothing about a stylesheet that shipped a whole keyframe list.
 * stylelint refuses `@keyframes` in the files this repository writes; a dependency, a plugin or a Tailwind
 * utility emitting one into the artifact is the case this covers. */
describe("a keyframe list in the bundle", () => {
  it.each([
    ["@keyframes fade{to{opacity:1}}", "a list whose every frame is a legal declaration"],
    ["@-webkit-keyframes fade{to{opacity:1}}", "the vendor spelling"],
    ["@KEYFRAMES fade{to{opacity:1}}", "the at-rule name in another case"],
  ])("%s is refused: %s", (css) => {
    const found = reasons(css);

    expect(found).toHaveLength(1);
    expect(found[0]).toContain("motion is zero");
  });

  /* A list whose frames ALSO declare a banned property is refused twice, and both findings are wanted: the
   * at-rule says the animation may not exist, and the declaration says `rotate` may not either. */
  it("is refused once for the list and once per banned frame", () => {
    const outcome = verdictFor("@keyframes spin{to{rotate:360deg}}");

    expect(outcome.findings.map((finding) => finding.check)).toEqual([
      "keyframes-in-the-bundle",
      "banned-declaration-in-the-bundle",
    ]);
  });

  it("is refused on the strength of the at-rule, since its frames declare nothing banned", () => {
    const outcome = verdictFor("@keyframes fade{from{opacity:0}to{opacity:1}}");

    expect(outcome.findings.map((finding) => finding.check)).toEqual(["keyframes-in-the-bundle"]);
  });

  it("names the line it shipped on, so a reader can find it in the artifact", () => {
    const outcome = verdictFor(".a{color:var(--ink)}\n@keyframes fade{to{opacity:1}}");

    expect(outcome.findings[0]?.line).toBe(2);
  });

  it.each([
    "@media (width >= 1536px){.a{color:var(--ink)}}",
    "@supports (color:red){.a{color:red}}",
  ])("leaves %s alone, because an at-rule is not a keyframe list", (css) => {
    expect(reasons(css)).toEqual([]);
  });
});

describe("what the check reports about itself", () => {
  it("states how many declarations it read, so a check that stopped reading is visible", () => {
    const outcome = verdictFor(".a{color:var(--ink)}.b{background-color:var(--paper)}");

    expect(outcome.notes.join("\n")).toContain("2 declaration(s)");
  });

  it("states how many at-rules it read, so a keyframe list cannot hide in an unread one", () => {
    const outcome = verdictFor(
      "@media print{.a{color:var(--ink)}}@supports (color:red){.b{color:red}}",
    );

    expect(outcome.notes.join("\n")).toContain("2 at-rule(s)");
  });

  it("states the size of what it examined", () => {
    expect(verdictFor(".a{color:var(--ink)}").notes.join("\n")).toMatch(/kB/);
  });

  /* The barrel figures are the other half of this gate's report, and a composed outcome that dropped them
   * would still pass every assertion above. */
  it("carries the barrel figure and its verdict into the same report", () => {
    const outcome = checkBundle({
      stylesheets: [{ file: "/dist/assets/probe.css", name: "probe.css", css: ".a{color:red}" }],
      barrels: [{ probe: BARREL_PROBES[0], throughBarrelBytes: 3_686, onItsOwnBytes: 3_686 }],
    });

    expect(outcome.notes.join("\n")).toContain("1 barrel(s)");
    expect(outcome.findings.map((finding) => finding.check)).toEqual([
      "barrel-loads-no-more-than-the-component",
    ]);
  });
});
