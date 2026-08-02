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
  /**
   * States this channel is specific to. Absent means it applies to any state.
   *
   * Needed because one property can carry two channels: `border-top-color` is the Area's 2px top
   * rule on a block and the quarter line's weight during a drag. Section 14's table distinguishes
   * them by the state, not by the property, so this model does too.
   */
  readonly states?: readonly string[] | undefined;
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
  /* THE GLYPH SLOT carries four occupants at once: the pinned mark, the proposal-source mark, the
   * overlap count and the origin mark. Section 14 settles its precedence in the week grid and warns
   * that the four must not collide. It is a channel like any other, so two files assigning it is the
   * same drift as two files assigning the fill.
   *
   * A glyph reaches the DOM as generated content or as a pseudo-element's own text, which is why the
   * properties are the `::before`/`::after` family rather than a colour. Ticket 8's pinned mark and
   * ticket 35's overlap count are the first two things that will claim it. */
  {
    name: "glyph slot",
    properties: ["content", "list-style-type", "list-style"],
    utilityPrefixes: ["content-", "before:content", "after:content"],
  },
  /* QUARTER-LINE WEIGHT belongs to `data-dragging` on the grid: at rest the quarter hour is drawn at
   * --grid-line-quarter and during a drag it steps up to hour weight, so the snap targets sharpen at
   * the one moment the user is aiming at them. A discrete state change, not motion. */
  {
    name: "quarter-line weight",
    properties: ["border-top-color", "border-bottom-color"],
    utilityPrefixes: ["border-t-", "border-b-"],
    states: ["data-dragging"],
  },
];

/* A state-specific channel is consulted first, so the drag's quarter-line weight is not read as the
 * Area's top rule. */
function matching(candidates: readonly Channel[], state: string): Channel | undefined {
  return (
    candidates.find((channel) => channel.states?.includes(state) === true) ??
    candidates.find((channel) => channel.states === undefined)
  );
}

export function channelFor(property: string, state: string): string | null {
  const candidates = CHANNELS.filter((channel) => channel.properties.includes(property));
  return matching(candidates, state)?.name ?? null;
}

export function channelForUtility(utility: string, state: string): string | null {
  const candidates = CHANNELS.filter((channel) =>
    channel.utilityPrefixes.some((prefix) => utility.startsWith(prefix)),
  );
  return matching(candidates, state)?.name ?? null;
}

/* States that are pseudo-classes rather than attributes, so they are not in the theme's variant
 * table but do own channels. Radix's own keyboard cursor is here because it maps to focus and
 * nothing else. */
export const PSEUDO_STATES = [":hover", ":focus-visible", "data-highlighted"] as const;
