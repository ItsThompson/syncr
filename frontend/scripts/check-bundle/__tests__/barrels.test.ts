/* THE BARREL PAYLOAD'S OWN VERDICT, over figures a build would have produced.
 *
 * Two things are asserted here that the shipped figures cannot assert about themselves. The first is that the
 * figure is printed at all, because a gate whose measurement quietly stops being reported is a gate that
 * certifies nothing. The second is the direction: both barrels state that importing one component may load
 * another's stylesheet, and a build in which it does not is a statement that has gone false. */

import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { BARREL_PROBES, checkBarrelPayloads, type BarrelPayload } from "../barrels.ts";

const domainProbe = BARREL_PROBES[0];

function payload(throughBarrelBytes: number, onItsOwnBytes: number): BarrelPayload {
  return { probe: domainProbe, throughBarrelBytes, onItsOwnBytes };
}

function checkNames(payloads: readonly BarrelPayload[]): string[] {
  return checkBarrelPayloads(payloads).findings.map((finding) => finding.check);
}

describe("the probes the figure is measured with", () => {
  it("covers both barrels, since a layer nobody probes has no figure", () => {
    expect(BARREL_PROBES.map((probe) => probe.barrel.replace(/.*\/src\//, "src/"))).toEqual([
      "src/ui/domain/index.ts",
      "src/ui/primitives/index.ts",
    ]);
  });

  it.each(BARREL_PROBES)("names files that exist, for $component", (probe) => {
    expect(existsSync(probe.barrel)).toBe(true);
    expect(existsSync(probe.module)).toBe(true);
  });
});

describe("a barrel that loads more than the component it was asked for", () => {
  it("produces no finding, because that is what the barrel says it does", () => {
    expect(checkNames([payload(31_405, 3_686)])).toEqual([]);
  });

  it("records both figures and the difference, so the cost is a measurement and not a claim", () => {
    const notes = checkBarrelPayloads([payload(31_405, 3_686)]).notes.join("\n");

    expect(notes).toContain("31.41 kB");
    expect(notes).toContain("3.69 kB");
    expect(notes).toContain("27.72 kB");
  });

  it("names the barrel and the module the two builds started from", () => {
    const notes = checkBarrelPayloads([payload(31_405, 3_686)]).notes.join("\n");

    expect(notes).toContain("frontend/src/ui/domain/index.ts");
    expect(notes).toContain("frontend/src/ui/domain/table/index.ts");
  });
});

describe("a barrel that loads no more than the component it was asked for", () => {
  it.each([
    [3_686, "the same CSS either way, which is a side-effect-free barrel"],
    [3_000, "less CSS through the barrel than without it"],
  ])("is refused at %i bytes: %s", (throughBarrelBytes) => {
    const findings = checkBarrelPayloads([payload(throughBarrelBytes, 3_686)]).findings;

    expect(findings.map((finding) => finding.check)).toEqual([
      "barrel-loads-no-more-than-the-component",
    ]);
    expect(findings[0]?.file).toBe(domainProbe.barrel);
    expect(findings[0]?.message).toContain("the statement is what has to change");
  });
});

/* A probe that resolves nothing builds nothing, and nothing is 0 kB. Reported as a saving it is the strongest
 * figure this gate could print and it would be an artefact of a broken probe, so it is refused instead. */
describe("a probe that emitted no stylesheet", () => {
  it.each([
    [0, 3_686],
    [31_405, 0],
    [0, 0],
  ])("is refused once, at %i and %i bytes", (throughBarrelBytes, onItsOwnBytes) => {
    expect(checkNames([payload(throughBarrelBytes, onItsOwnBytes)])).toEqual([
      "barrel-payload-unmeasured",
    ]);
  });
});

describe("what the barrel check reports about itself", () => {
  it("states how many barrels it built, so a run that measured none is visible", () => {
    expect(checkBarrelPayloads([]).notes.join("\n")).toContain("0 barrel(s)");
    expect(checkBarrelPayloads([payload(31_405, 3_686)]).notes.join("\n")).toContain("1 barrel(s)");
  });
});
