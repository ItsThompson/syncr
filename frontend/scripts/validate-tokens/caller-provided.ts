/* What `@caller-provided` may and may not excuse.
 *
 * The annotation states a contract: the token layer references a property it deliberately does not
 * declare, because the element that draws with it supplies the value. That contract is satisfiable
 * only where CSS lets a caller reach the reference.
 *
 * A `var()` is substituted against the element the declaration is written on. So a reference inside
 * a `:root` block reads the root element's own value, and no element further down the tree can
 * supply it: the annotation would excuse a property that resolves to nothing everywhere. A reference
 * on an ordinary rule is substituted on the element that rule matches, which is the element the
 * contract names, so there the annotation holds.
 *
 * An annotation the layer resolves at `:root` is therefore refused rather than honored, and the
 * names it covers dangle like any other undeclared property. */

import type { ScannedStylesheet } from "../lib/css-scan.ts";
import { locate, type Finding } from "../lib/findings.ts";
import { relativeToRepo } from "../lib/paths.ts";

export interface CallerProvidedContracts {
  /** Annotated names a caller can still supply, so a reference to one resolves rather than dangles. */
  readonly honored: ReadonlySet<string>;
  /** One finding per annotation the layer resolves itself, positioned on the annotation. */
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

  const honored = new Set(annotations.keys());
  const refusals: Finding[] = [];
  for (const { file, scan } of tokenLayer) {
    for (const reference of scan.varReferences) {
      if (!reference.substitutedAtRoot) continue;
      const annotation = annotations.get(reference.name);
      if (annotation === undefined || !honored.has(reference.name)) continue;
      honored.delete(reference.name);
      const site = locate(relativeToRepo(file), reference.line, reference.column);
      refusals.push(refusal(reference.name, annotation, site));
    }
  }
  return { honored, refusals };
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
      `element a caller styles can supply it. Declare ${name}, or move the reference onto the ` +
      "rule that paints.",
  };
}
