/* The state channels, and what carries each one.
 *
 * A channel is the visual property a state spends. The rule the kit is built on is that a state
 * owns exactly one channel, so combinations add instead of overwrite.
 *
 * WHAT THIS ASSERTS, AND WHY IT IS THE PAIR RATHER THAN THE CHANNEL ALONE. Section 14's channel
 * table deals several states onto one channel on purpose: the fill carries the block's existence,
 * hover, the frame and the current nav item, and the left rule carries conflict, selected and
 * split. So "one file per channel" is not implementable against the table it comes from. What IS
 * checkable, and what the rule is actually protecting, is the PAIR: a given state's given channel
 * is assigned in exactly one file. Two files assigning hover's fill is how two surfaces come to
 * disagree about what hover looks like, and nothing on a rendered screen reveals the disagreement
 * until the two states co-occur.
 *
 * A channel is assigned either by a CSS declaration inside a rule that selects on a state, or by a
 * variant-prefixed utility in markup. Both are read, because a rule enforced on only one of them is
 * bypassed by writing the other. */

export interface Channel {
  readonly name: string;
  /** CSS properties that carry the channel. */
  readonly properties: readonly string[];
  /** Tailwind utility prefixes that carry the channel. */
  readonly utilityPrefixes: readonly string[];
}

export const CHANNELS: readonly Channel[] = [
  {
    name: "fill",
    properties: ["background-color", "background"],
    utilityPrefixes: ["bg-"],
  },
  {
    name: "fill as image",
    properties: ["background-image"],
    utilityPrefixes: ["bg-[url", "bg-gradient", "bg-linear"],
  },
  {
    name: "top rule",
    properties: ["border-top", "border-top-color", "border-top-width", "border-top-style"],
    utilityPrefixes: ["border-t"],
  },
  {
    name: "left rule",
    properties: ["border-left", "border-left-color", "border-left-width", "border-left-style"],
    utilityPrefixes: ["border-l"],
  },
  {
    name: "outline",
    properties: ["outline", "outline-color", "outline-offset", "outline-width", "outline-style"],
    utilityPrefixes: ["outline"],
  },
  {
    name: "type size and padding",
    properties: ["font-size", "padding", "padding-top", "padding-bottom", "line-height"],
    utilityPrefixes: ["text-", "p-", "pt-", "pb-", "leading-"],
  },
];

/* States that are pseudo-classes rather than attributes, so they are not in the theme's variant
 * table but do own channels. Radix's own keyboard cursor is here because it maps to focus and
 * nothing else. */
export const PSEUDO_STATES = [":hover", ":focus-visible", "data-highlighted"] as const;

export function channelFor(property: string): string | null {
  const channel = CHANNELS.find((candidate) => candidate.properties.includes(property));
  return channel?.name ?? null;
}

export function channelForUtility(utility: string): string | null {
  const channel = CHANNELS.find((candidate) =>
    candidate.utilityPrefixes.some((prefix) => utility.startsWith(prefix)),
  );
  return channel?.name ?? null;
}
