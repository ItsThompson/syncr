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
 * Note which zones may read the api's TYPES: `domain` only. A Problem or a Resource is a domain
 * concept, so a primitive or a layout container that needs to name one is misfiled rather than
 * under-permitted. Writing this out is what corrected a forward constraint I had stated as "the kit
 * may read the api's types": the config has always been stricter than that, and the generated
 * matrix is what surfaced the disagreement. */
export const CAPABILITIES: readonly Capability[] = [
  {
    capability: "the fetch client",
    // The bare barrel reaches it too, because `api/index` could re-export the client later.
    specifiers: ["../../api", "../../api/client"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "the SWR key registry, and so cache invalidation",
    specifiers: ["../../api/keys"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "a data hook",
    specifiers: ["../../api/hooks", "../../api/hooks/useWeek"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "a route",
    specifiers: ["../../routes", "../../routes/WeekRoute"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "the application shell and its session",
    specifiers: ["../../app", "../../app/signIn", "../../app/GatedShell"],
    permittedZones: NO_ZONE,
  },
  {
    capability: "the api's types",
    specifiers: ["../../api/problem", "../../api/resource"],
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
  return KIT_LAYERS.find((layer) => specifier.startsWith(`../${layer}`)) ?? null;
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
