/* WHAT THE KIT'S ZONES DENY, stated as capabilities and as every path that reaches each one.
 *
 * This file exists because the same defect landed twice, and both times for the same reason: the
 * rule was written against the MECHANISM a component would use rather than against the CAPABILITY
 * the rule denies. "Never import domain" became a glob that missed a barrel import. "Never reach a
 * hook" became a group that permitted `api/client`, which is the thing that actually fetches.
 *
 * So the probe matrix is no longer a list of shapes someone thought of. It is the cross product of
 * every zone with every specifier below, and each expected verdict is DERIVED from this table
 * rather than written beside the row. Adding a zone, a layer, or a path to a capability extends the
 * matrix automatically, which is what makes the next instance of this class fail a test. */

/** The kit's layers, lowest first. A zone may import its own layer and any lower one. */
export const KIT_LAYERS = ["primitives", "layout", "domain"] as const;

export type KitZone = (typeof KIT_LAYERS)[number];

export interface Capability {
  /** What a component would be able to do, named as the rule's own message names it. */
  readonly capability: string;
  /** Every import specifier that reaches it, from `src/ui/<zone>/`, barrels included. */
  readonly specifiers: readonly string[];
  /** The zones permitted to reach it. Empty means no zone may. */
  readonly permittedZones: readonly KitZone[];
}

const NO_ZONE: readonly KitZone[] = [];
const EVERY_ZONE = KIT_LAYERS;

/* One table, and it is the whole policy for everything outside the kit's own layers.
 *
 * EVERY SPECIFIER LISTED IS A SHAPE THE LANGUAGE PERMITS, not a shape someone thought of. That
 * distinction is the whole reason this file exists: a rule enumerating `api/client` permitted
 * `api/client.ts`, `api/keys.js` and `api/index`, because `allowImportingTsExtensions` is on and
 * `moduleResolution: bundler` resolves a `.js` specifier to a `.ts` file. So each capability lists
 * the barrel, the plain module, the explicit `.ts` form and the `.js` form, and the config denies the
 * DIRECTORY rather than any of them individually. The list is the test's coverage, not the fence.
 *
 * `contract/` is the one directory a `domain` component may read: it holds the Problem and Resource
 * types a component renders and nothing that fetches. It is a separate directory from `api/`
 * precisely so the fence can be directory-shaped. */
export const CAPABILITIES: readonly Capability[] = [
  {
    capability: "the fetch client",
    specifiers: [
      "../../api",
      "../../api/index",
      "../../api/client",
      "../../api/client.ts",
      "../../api/client.js",
    ],
    permittedZones: NO_ZONE,
  },
  {
    capability: "the SWR key registry, and so cache invalidation",
    specifiers: ["../../api/keys", "../../api/keys.ts", "../../api/keys.js"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "a data hook",
    specifiers: ["../../api/hooks", "../../api/hooks/index", "../../api/hooks/useWeek"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "the generated schema, which is the fetching layer's own input",
    specifiers: ["../../api/schema"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "a route",
    specifiers: ["../../routes", "../../routes/index", "../../routes/WeekRoute"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "the application shell and its session",
    specifiers: ["../../app", "../../app/index", "../../app/signIn", "../../app/GatedShell"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "the wire contract's types",
    specifiers: [
      "../../contract",
      "../../contract/index",
      "../../contract/problem",
      "../../contract/resource",
    ],
    permittedZones: ["domain"],
  },
  {
    capability: "shared library code",
    specifiers: ["../../lib/keyboard"],
    permittedZones: EVERY_ZONE,
  },
  {
    capability: "a package",
    specifiers: ["react", "swr", "react-router"],
    permittedZones: EVERY_ZONE,
  },
  {
    capability: "a sibling in its own layer",
    specifiers: ["./navigation", "./Button"],
    permittedZones: EVERY_ZONE,
  },
];

/** Every import specifier that reaches one kit layer from another, barrel and deep form. */
export function layerSpecifiers(layer: KitZone): string[] {
  return [`../${layer}`, `../${layer}/Thing`, `../${layer}/Thing/Thing`];
}

/** The layer a specifier reaches, or null when it names none. */
function targetLayer(specifier: string): KitZone | null {
  // Boundary-checked rather than a bare prefix, so a sibling named `layoutish` is not read as
  // `layout`. No such directory exists; the model should still not be able to misclassify one.
  return (
    KIT_LAYERS.find(
      (layer) => specifier === `../${layer}` || specifier.startsWith(`../${layer}/`),
    ) ?? null
  );
}

/** The policy, as one predicate: a zone may reach its own layer, any lower one, and what the table permits it. */
export function isRefusedByPolicy(zone: KitZone, specifier: string): boolean {
  const layer = targetLayer(specifier);
  if (layer !== null) return KIT_LAYERS.indexOf(layer) > KIT_LAYERS.indexOf(zone);

  const capability = CAPABILITIES.find((candidate) => candidate.specifiers.includes(specifier));
  if (capability === undefined) {
    throw new Error(
      `${specifier} names no capability. Add it to CAPABILITIES rather than guessing.`,
    );
  }
  return !capability.permittedZones.includes(zone);
}

/** Every specifier the policy knows, which is what the probe matrix crosses with each zone. */
export function everySpecifier(): string[] {
  return [
    ...KIT_LAYERS.flatMap((layer) => layerSpecifiers(layer)),
    ...CAPABILITIES.flatMap((capability) => capability.specifiers),
  ];
}
