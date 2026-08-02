/* The kit's import zones, proved to fail.
 *
 * Every case below was verified to escape the original globs or to be correctly allowed. The four
 * refused shapes are the ones this codebase already writes elsewhere, which is why the hole
 * mattered: `routes/index.tsx` deep-imports `ui/domain/shell/navigation`, and `App.tsx` imports the
 * `../routes` barrel. */

import { describe, expect, it } from "vitest";

import { lintZoneProbes, type ZoneProbe } from "../probe.ts";

const PROBES: readonly ZoneProbe[] = [
  // primitives may import nothing above it, by barrel or by deep path.
  { zone: "primitives", specifier: "../domain/shell", isRefused: true },
  { zone: "primitives", specifier: "../domain/shell/SidebarNav", isRefused: true },
  { zone: "primitives", specifier: "../layout", isRefused: true },
  { zone: "primitives", specifier: "../layout/Panel/Panel", isRefused: true },
  // No kit zone may know a route, the app, or the api.
  { zone: "primitives", specifier: "../../routes", isRefused: true },
  { zone: "primitives", specifier: "../../routes/WeekRoute", isRefused: true },
  { zone: "primitives", specifier: "../../app", isRefused: true },
  { zone: "primitives", specifier: "../../app/signIn", isRefused: true },
  { zone: "primitives", specifier: "../../api/client", isRefused: true },
  // layout may import primitives, and nothing above it.
  { zone: "layout", specifier: "../primitives/Button", isRefused: false },
  { zone: "layout", specifier: "../domain", isRefused: true },
  { zone: "layout", specifier: "../domain/week-grid/Block", isRefused: true },
  { zone: "layout", specifier: "../../routes", isRefused: true },
  // domain may import both lower zones and the api's TYPES, but never a hook.
  { zone: "domain", specifier: "../layout/Panel", isRefused: false },
  { zone: "domain", specifier: "../primitives/Button", isRefused: false },
  { zone: "domain", specifier: "../../api/problem", isRefused: false },
  { zone: "domain", specifier: "../../api/hooks", isRefused: true },
  { zone: "domain", specifier: "../../api/hooks/useWeek", isRefused: true },
  { zone: "domain", specifier: "../../app", isRefused: true },
  // Everything outside the zones stays reachable from the kit.
  { zone: "domain", specifier: "../../lib/keyboard", isRefused: false },
  { zone: "primitives", specifier: "react", isRefused: false },
  { zone: "primitives", specifier: "./Button", isRefused: false },
];

describe("the kit's import zones", () => {
  /* One oxlint run for every probe: spawning the binary once per case would dominate the suite. */
  const results = lintZoneProbes(PROBES);

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
});
