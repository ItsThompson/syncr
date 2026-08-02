/* The kit's import zones, proved to fail, over the whole zone-by-capability matrix.
 *
 * Iteration 1 fixed the globs for the shapes a reviewer and I had thought of. Iteration 2 found the
 * same defect class one directory over, in a target neither of us had listed. So the cases are no
 * longer a list: they are every zone crossed with every specifier the policy names, and each
 * expected verdict is derived from `isRefusedByPolicy` rather than written beside the row.
 *
 * Adding a zone, a layer, or a path to a capability extends this matrix without touching the test,
 * and a specifier that names no capability throws rather than defaulting to allowed. */

import { describe, expect, it } from "vitest";

import {
  CAPABILITIES,
  KIT_LAYERS,
  everySpecifier,
  isRefusedByPolicy,
  type KitZone,
} from "../policy.ts";
import { lintZoneProbes, type ZoneProbe } from "../probe.ts";

const PROBES: ZoneProbe[] = KIT_LAYERS.flatMap((zone) =>
  everySpecifier().map((specifier) => ({
    zone,
    specifier,
    isRefused: isRefusedByPolicy(zone, specifier),
  })),
);

describe("the kit's import zones", () => {
  /* One oxlint run for the whole matrix: spawning the binary per case would dominate the suite. */
  const results = lintZoneProbes(PROBES);

  it("crosses every zone with every specifier the policy names", () => {
    expect(PROBES).toHaveLength(KIT_LAYERS.length * everySpecifier().length);
  });

  it.each(PROBES.map((probe) => [probe.zone, probe.specifier, probe.isRefused] as const))(
    "%s importing %s is refused: %s",
    async (zone, specifier, isRefused) => {
      const result = (await results).find(
        (candidate) => candidate.zone === zone && candidate.specifier === specifier,
      );
      expect(result?.wasRefused).toBe(isRefused);
    },
  );

  it("refuses something, so a config that lints nothing cannot pass this file", async () => {
    expect((await results).filter((result) => result.wasRefused).length).toBeGreaterThan(0);
  });

  it("permits something, so a config that refuses everything cannot pass either", async () => {
    expect((await results).filter((result) => !result.wasRefused).length).toBeGreaterThan(0);
  });
});

describe("the policy itself", () => {
  it.each(KIT_LAYERS)("%s may import its own layer", (zone: KitZone) => {
    expect(isRefusedByPolicy(zone, `../${zone}/Thing`)).toBe(false);
  });

  it("lets domain reach both lower layers", () => {
    expect(isRefusedByPolicy("domain", "../layout/Thing")).toBe(false);
    expect(isRefusedByPolicy("domain", "../primitives/Thing")).toBe(false);
  });

  it("keeps primitives out of both higher layers", () => {
    expect(isRefusedByPolicy("primitives", "../layout")).toBe(true);
    expect(isRefusedByPolicy("primitives", "../domain")).toBe(true);
  });

  it("keeps layout out of domain but not out of primitives", () => {
    expect(isRefusedByPolicy("layout", "../domain")).toBe(true);
    expect(isRefusedByPolicy("layout", "../primitives")).toBe(false);
  });

  it("throws on a specifier no capability names, rather than defaulting to allowed", () => {
    expect(() => isRefusedByPolicy("domain", "../../invented/thing")).toThrow(
      /names no capability/,
    );
  });

  it.each(
    CAPABILITIES.filter((capability) => capability.permittedZones.length === 0).flatMap(
      (capability) => capability.specifiers,
    ),
  )("denies %s to every zone", (specifier) => {
    for (const zone of KIT_LAYERS) expect(isRefusedByPolicy(zone, specifier)).toBe(true);
  });

  it("permits the api's types to domain and to no other zone", () => {
    for (const specifier of ["../../api/problem", "../../api/resource"]) {
      expect(isRefusedByPolicy("domain", specifier)).toBe(false);
      expect(isRefusedByPolicy("layout", specifier)).toBe(true);
      expect(isRefusedByPolicy("primitives", specifier)).toBe(true);
    }
  });
});
