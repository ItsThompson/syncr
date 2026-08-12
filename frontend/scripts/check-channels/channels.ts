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
 * bypassed by writing the other.
 *
 * AND WHAT THE MODEL DOES NOT NAME IS A FINDING, NOT A PERMISSION. `channelFor` returning null used to
 * mean "not a channel", so a state spending a property nobody had modelled was not merely unassigned:
 * it was unseen, and a row could take a third declaration with this check, the combination matrix and the
 * layer rules all green. `UNCHANNELLED` is the other half of the model: a property spent by a state either
 * carries a channel or is named there with the reason it carries none. Silence is what the check reports. */

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
   * properties are the `::before`/`::after` family rather than a colour.
   *
   * `--glyph` is here because that is what the kit's glyph table actually assigns. `glyphs.css` states
   * `content: var(--glyph)` once, on the slot, and a state switches the MARK by setting `--glyph`: a row
   * becoming at risk is `[data-at-risk]` setting that property. Reading only
   * `content` would have called the glyph slot unassigned while a state was driving it, which is a
   * check reporting a claim rather than a fact. */
  {
    name: "glyph slot",
    properties: ["content", "--glyph", "list-style-type", "list-style"],
    utilityPrefixes: ["content-", "before:content", "after:content"],
  },
  /* THE BOTTOM RULE. An active tab takes it at --rule-emphasis, the tertiary button's hover solidifies it
   * rather than spending a fill, and a disabled select item dashes it. Three surfaces, one channel, and the
   * drag's quarter-line weight below claims the same properties for `data-dragging` alone. */
  {
    name: "bottom rule",
    properties: [
      "border-bottom",
      "border-bottom-color",
      "border-bottom-width",
      "border-bottom-style",
    ],
    utilityPrefixes: ["border-b"],
  },
  /* THE CONTROL BORDER, all four edges at once. A field's border is the only thing marking where the control
   * begins, so disabled dashes it and mutes it rather than changing the fill. */
  {
    name: "control border",
    properties: ["border", "border-color", "border-style", "border-width"],
    utilityPrefixes: ["border-dashed", "border-solid", "border-dotted"],
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
  /* HIDDEN UNTIL FOCUSED is the one channel whose resting value is invisibility, so it is the only one a
   * reader compares against nothing: the control is not there, and then it is. A control that must be
   * reachable before it is seen is clipped to a 1px box rather than removed, and the reveal restores its
   * own box, so the treatment spends geometry rather than a mark.
   *
   * SCOPED TO THE FOCUS STATE, because all six properties are ordinary geometry under every other state and
   * an unscoped entry would read a hovered row's own box as a reveal. `position` is named as carrying no
   * channel for any state and a state-specific channel is consulted first, so the reveal takes it under
   * focus while everywhere else it stays the stacking context the keyboard cursor's inset ring needs.
   *
   * `:focus-visible` IS THE STATE, AND THE OTHER SPELLINGS OF FOCUS ARE NOT INTERCHANGEABLE WITH IT.
   * `statesInSelector` finds only the pseudo-classes `PSEUDO_STATES` lists, so a rule under any other
   * member of the focus family, `:focus` and `:focus-within` included, is unseen rather than checked. It
   * also matches by substring, so `:not(:focus-visible)` reads AS the focus state: a rule that applies
   * only while the control is not focused is counted as a reveal, with every declaration in it. Write the
   * resting half under no state at all, which is what makes it geometry to this model.
   *
   * THE UTILITY PREFIXES ARE THE TWO THAT CARRY THE WHOLE TREATMENT, not `w-`, `m-` or `overflow-`, which
   * carry geometry under a state and would report a width as a reveal. A bare `sr-only` records nothing,
   * because a utility is read only through a variant, which is what keeps the permanently-hidden sites out
   * of this channel: they never reveal, and permanently hidden is a different state. */
  {
    name: "hidden until focused",
    properties: ["position", "width", "height", "overflow", "clip-path", "margin"],
    utilityPrefixes: ["sr-only", "not-sr-only"],
    states: [":focus-visible"],
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

export interface Unchannelled {
  readonly property: string;
  /** Why the property carries no channel. Printed in the finding, so the decision travels with the refusal. */
  readonly reason: string;
  /**
   * States that may spend it. Absent means any state may.
   *
   * Stated per state where the property is legitimate for one state and was a real defect for another: the
   * control families mute their own label under `disabled`, and a current ROW spending the same `color` was
   * a third declaration on a state the channel table deals two, which nothing could see.
   */
  readonly states?: readonly string[] | undefined;
}

export const UNCHANNELLED: readonly Unchannelled[] = [
  {
    property: "position",
    reason:
      "it is the stacking context the keyboard cursor's inset ring needs, not a mark a reader sees",
  },
  {
    property: "z-index",
    reason: "it orders two surfaces and draws nothing of its own",
  },
  {
    property: "cursor",
    reason: "it is a pointer affordance: invisible in a rendering and absent from a keyboard",
  },
  {
    property: "color",
    states: ["data-disabled", "data-state"],
    reason:
      "text ink is not a channel. A control family mutes its own label under disabled, so modelling it " +
      "would report three files as drift for a state that legitimately does it everywhere. It is granted " +
      "per state rather than outright, because a ROW spending it is the defect this entry exists to keep " +
      "visible. The grant to `data-state` is wider than the one rule that needs it, the active tab's ink: " +
      '`statesInSelector` reads the attribute without its value, so `data-state="active"` cannot be ' +
      "named on its own until the model carries values",
  },
];

/** Why a state may spend a property that carries no channel, or null when the model does not permit it. */
export function unchannelledReason(property: string, state: string): string | null {
  const named = UNCHANNELLED.filter((entry) => entry.property === property);
  const entry =
    named.find((candidate) => candidate.states?.includes(state) === true) ??
    named.find((candidate) => candidate.states === undefined);
  return entry?.reason ?? null;
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
