/* THE DECLARATIONS THE DESIGN LANGUAGE FORBIDS, IN ONE PLACE.
 *
 * Four consumers ask the same question of four different inputs, and each one used to carry its own
 * copy of the answer:
 *
 *   stylelint            a declaration written in a stylesheet
 *   the emitted verdict  a declaration a utility compiles to
 *   the inline-style rule a declaration written as a TSX object property
 *   the bundle gate      a declaration in the stylesheet a browser downloads
 *
 * Three copies is how a shape gets caught in one input and missed in another, which is what happened:
 * `STYLE_VIOLATIONS` enumerated `transform:` and `filter:` in their CSS spelling while React writes
 * `willChange` and `backdropFilter`, so a rendered blur passed every check. A property added to the
 * design language now reaches every input by one edit here.
 *
 * stylelint keeps its own list, because its config is data a stylelint process reads rather than a
 * module it can import. A test asserts the two sets are equal, which is the same mechanism the theme's
 * colour namespace and the two breakpoint literals are pinned by. */

/** Motion is zero, without exception. Mirrors `stylelint.config.mjs`'s `property-disallowed-list`. */
export const BANNED_PROPERTIES: ReadonlySet<string> = new Set([
  "transition",
  "transition-property",
  "transition-duration",
  "transition-timing-function",
  "transition-delay",
  "transition-behavior",
  "animation",
  "animation-name",
  "animation-duration",
  "animation-timing-function",
  "animation-delay",
  "animation-iteration-count",
  "transform",
  "translate",
  "rotate",
  "scale",
  "will-change",
]);

/* Print has no blur. The two vendor spellings are here because React writes `WebkitFilter` and
 * Tailwind emits `-webkit-backdrop-filter` beside the unprefixed one, and a set that holds only the
 * modern spelling refuses neither. */
export const FILTER_PROPERTIES: ReadonlySet<string> = new Set([
  "filter",
  "backdrop-filter",
  "-webkit-filter",
  "-webkit-backdrop-filter",
]);

/* Tailwind routes a utility's shadow through this custom property, so that is where a `shadow-*`
 * value has to be read: the `box-shadow` a utility emits is always the same composition of
 * `--tw-*` variables. An arbitrary property skips that machinery and writes `box-shadow` directly. */
const SHADOW_CARRIER = "--tw-shadow";
const COMPOSED_FROM_VARIABLES = "var(--tw-";
const LEGAL_SHADOW_VALUES = new Set(["var(--shadow-hard)", "none", "0 0 #0000"]);

/** `animation: none` is the one legal motion value, which is why `--animate-none` is mapped at all. */
const LEGAL_MOTION_VALUES = new Set(["none"]);

/* Removing the ring without an equivalent replacement leaves a keyboard-first tool with no focus
 * indicator. The ring itself is legal: `base.css` draws it, so `outline: var(--state-focus-ring)` has
 * to survive every one of these consumers.
 *
 * THE LONGHANDS ARE HERE BECAUSE A UTILITY REACHES THEM AND NOT THE SHORTHAND. `outline-none` compiles
 * to `outline-style: none`, so a rule written only against `outline: none` refuses the CSS spelling and
 * permits the class every Radix example reaches for. */
const REMOVED_OUTLINE: Readonly<Record<string, ReadonlySet<string>>> = {
  outline: new Set(["none", "0"]),
  "outline-style": new Set(["none", "hidden"]),
  "outline-width": new Set(["0", "0px"]),
};

/**
 * Why the design language refuses this declaration, or null when it permits it.
 *
 * The reason names the RULE and not the declaration: every caller already holds the property and the
 * value it read, and a caller that echoes them plus a reason that echoes them again reads as a stutter.
 *
 * Only the absolutes live here: a rule that depends on WHICH file the declaration is in, such as the
 * radius allowlist, belongs to the check that knows the file.
 */
export function refusalFor(property: string, value: string): string | null {
  const name = property.trim().toLowerCase();
  const normalized = value.replace(/\s+/g, " ").trim();

  if (FILTER_PROPERTIES.has(name)) return "print has no blur";

  if (BANNED_PROPERTIES.has(name) && !LEGAL_MOTION_VALUES.has(normalized)) {
    return "motion is zero, without exception";
  }

  if (name === SHADOW_CARRIER && !LEGAL_SHADOW_VALUES.has(normalized)) {
    return "the system has one shadow, --shadow-hard, and print has no blur";
  }

  if (
    name === "box-shadow" &&
    !normalized.includes(COMPOSED_FROM_VARIABLES) &&
    !LEGAL_SHADOW_VALUES.has(normalized)
  ) {
    return "the system has one shadow, --shadow-hard, and print has no blur";
  }

  if (REMOVED_OUTLINE[name]?.has(normalized) === true) {
    return "the system draws its own focus ring, and removing one leaves a keyboard-first tool with none";
  }

  return null;
}

/**
 * The CSS property name React writes for a style-object key.
 *
 * A style object is camelCase and every rule that read it was written in CSS spelling, so
 * `backdropFilter`, `willChange` and `WebkitFilter` passed a check that refuses `backdrop-filter`,
 * `will-change` and `-webkit-filter`. Converting the key is what makes one list serve both.
 */
export function cssPropertyFor(styleKey: string): string {
  if (styleKey.startsWith("--")) return styleKey;
  const hyphenated = styleKey.replace(/[A-Z]/g, (character) => `-${character.toLowerCase()}`);
  // A leading capital is React's vendor-prefix form, `WebkitFilter`, and hyphenating it already
  // produced the leading dash. `ms` is the one prefix React spells lowercase.
  if (/^ms[A-Z]/.test(styleKey)) return `-${hyphenated}`;
  return hyphenated;
}
