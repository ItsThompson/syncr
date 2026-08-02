/* The closed state vocabulary, read from the one place that declares it.
 *
 * `theme.css`'s `@custom-variant` set IS the vocabulary. Two checks need it, the markup scan to
 * refuse an attribute outside it and the channel assertion to map a variant onto the state it
 * stands for, and they had two readers of one file with two different strictnesses: one matched
 * any `data-*` anywhere in the text, so a `data-*` name mentioned only in a COMMENT silently
 * widened the vocabulary and made an invented attribute legal.
 *
 * One parser now, and it reads declarations only: comments are blanked before the scan. That also
 * makes the markup scan's failure message literal, since it tells the author to declare a
 * `@custom-variant` and that is now exactly what the check looks for. */

import { codeWithoutComments } from "./css-scan.ts";

export interface CustomVariant {
  /** The variant name a component writes before the colon, as in `pinned:bg-paper`. */
  readonly name: string;
  /** The selector the variant expands to. */
  readonly selector: string;
  /** The `data-*` attribute the selector keys on, absent for a variant that keys on nothing. */
  readonly attribute?: string | undefined;
}

const CUSTOM_VARIANT = /@custom-variant\s+([a-z][a-z0-9-]*)\s*\(([^)]*)\)/g;
const DATA_ATTRIBUTE = /data-[a-z][a-z0-9-]*/;

export function parseCustomVariants(themeSource: string): CustomVariant[] {
  const declarations = codeWithoutComments(themeSource);
  const variants: CustomVariant[] = [];
  for (const match of declarations.matchAll(CUSTOM_VARIANT)) {
    const attribute = DATA_ATTRIBUTE.exec(match[2]);
    variants.push({
      name: match[1],
      selector: match[2].trim(),
      attribute: attribute?.[0],
    });
  }
  return variants;
}

/** Every `data-*` attribute a component may write. */
export function vocabularyOf(themeSource: string): Set<string> {
  const attributes = new Set<string>();
  for (const variant of parseCustomVariants(themeSource)) {
    if (variant.attribute !== undefined) attributes.add(variant.attribute);
  }
  return attributes;
}
