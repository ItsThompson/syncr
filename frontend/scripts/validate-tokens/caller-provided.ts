/* What `@caller-provided` may and may not excuse.
 *
 * The annotation states a contract: the token layer references a property it deliberately does not
 * declare, because the element that draws with it supplies the value. That contract is satisfiable
 * only where CSS lets the drawing element reach the reference.
 *
 * A `var()` is substituted against the element the declaration is written on. So a reference inside
 * a `:root` block reads the root element's own value, and no element below the root can supply it.
 * Styling the root itself does reach such a reference, measured in Chromium, but the root is never
 * the element that draws, so the contract still cannot hold. A reference on an ordinary rule is
 * substituted on the element that rule matches, which is the element the contract names, so there
 * the annotation holds.
 *
 * An annotation the layer resolves at `:root` is therefore refused rather than honored, and the
 * names it covers dangle like any other undeclared property. */

import type { ScannedStylesheet } from "../lib/css-scan.ts";
import { locate, type Finding } from "../lib/findings.ts";
import { relativeToRepo } from "../lib/paths.ts";

export interface CallerProvidedContracts {
  /** Annotated names a caller can still supply, so a reference to one resolves rather than dangles. */
  readonly honored: ReadonlySet<string>;
  /** Annotated names the layer resolves itself, which no annotation can excuse. */
  readonly refused: ReadonlySet<string>;
  /** One finding per refused name, positioned on the annotation. */
  readonly refusals: readonly Finding[];
}

interface Annotation {
  readonly file: string;
  readonly line: number;
  readonly column: number;
}

/** Reads the contracts out of the token layer and settles which of them the layer has broken. */
export function callerProvidedContracts(
  tokenLayer: readonly ScannedStylesheet[],
): CallerProvidedContracts {
  const annotations = new Map<string, Annotation>();
  for (const { file, scan } of tokenLayer) {
    for (const annotation of scan.callerProvided) {
      if (annotations.has(annotation.name)) continue;
      annotations.set(annotation.name, { file, line: annotation.line, column: annotation.column });
    }
  }

  const refused = new Set<string>();
  const refusals: Finding[] = [];
  for (const { file, scan } of tokenLayer) {
    for (const reference of scan.varReferences) {
      if (!reference.substitutedAtRoot) continue;
      if (refused.has(reference.name)) continue;
      const annotation = annotations.get(reference.name);
      if (annotation === undefined) continue;
      refused.add(reference.name);
      const site = locate(relativeToRepo(file), reference.line, reference.column);
      refusals.push(refusal(reference.name, annotation, site));
    }
  }

  const honored = new Set([...annotations.keys()].filter((name) => !refused.has(name)));
  return { honored, refused, refusals };
}

function refusal(name: string, annotation: Annotation, site: string): Finding {
  return {
    file: annotation.file,
    line: annotation.line,
    column: annotation.column,
    check: "caller-provided-refused",
    message:
      `@caller-provided ${name} is refused. The token layer resolves var(${name}) itself at ` +
      `${site}, inside a :root block, where CSS substitutes it against the root element, so no ` +
      `element below the root can supply it and the root is not the element that draws. Declare ` +
      `${name}, or move the reference onto the rule that paints.`,
  };
}
