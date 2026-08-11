/* THE GATE ON THE BYTES A BROWSER DOWNLOADS.
 *
 * Every other check here reads source and reasons about what the build will do with it. This one
 * reads the built stylesheet, which makes it immune to every question about extraction: a comment, a
 * plain string, a `__fixtures__` file, an `@apply`, and whatever Tailwind spells next all reach the
 * artifact or they do not.
 *
 * It exists because three review iterations called the stylesheet clean while it shipped
 * `box-shadow: 0 0 8px red`, `rotate:`, `--tw-blur` and `backdrop-filter`, each one sourced from a
 * file written to PROVE that shape is refused. The content scan was narrowed in response, and the
 * narrowing was itself an enumeration of files: `@source` matched a set and the markup scan's
 * `filesUnder` ignored a different set, so a utility named in a test's string or in a comment still
 * compiled into the bundle with all seven checks green. `backdrop-filter` was in the stylesheet a
 * browser downloaded, from the comment documenting the incident.
 *
 * The same artifact answers what a barrel's stylesheet side effect costs, which is why the two barrel
 * payloads are judged here rather than described in a comment somewhere: see `barrels.ts`.
 *
 * So the oracle is the artifact, and the declarations are parsed by postcss rather than by a pattern
 * written here. That matters more than it sounds: the previous survey of this same stylesheet with a
 * regex reported `rotate:`, `scale:` and `filter:` from inside `--tw-backdrop-hue-rotate`,
 * `--tw-backdrop-grayscale` and `--tw-backdrop-blur`, and `transform:` from `text-transform`. Every
 * one was a false positive, and a check that cries wolf four times gets its output ignored. */

import { parse, type AtRule, type Declaration, type Node, type Rule } from "postcss";

import { checkBarrelPayloads, type BarrelPayload } from "./barrels.ts";
import { asKb } from "../lib/bytes.ts";
import { refusalFor } from "../lib/declarations.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";

export interface BuiltStylesheet {
  /** Absolute path the asset takes in `dist/`, so a finding names a file a reader can open. */
  readonly file: string;
  /** The asset's name in the build output. */
  readonly name: string;
  readonly css: string;
}

export interface CheckBundleInput {
  readonly stylesheets: readonly BuiltStylesheet[];
  /** What each barrel's side effect built to. Declared rather than optional, so a run that measured none says so. */
  readonly barrels: readonly BarrelPayload[];
}

/** The selector chain a declaration sits under, so a finding names something a reader can grep for. */
function contextOf(declaration: Declaration): string {
  const path: string[] = [];
  let node: Node | undefined = declaration.parent;
  while (node !== undefined) {
    if (node.type === "rule") path.unshift((node as Rule).selector);
    // An at-rule is named too, because `.a` inside a media query and `.a` outside it are two
    // different declarations and a finding that reports only `.a` sends the reader to the wrong one.
    if (node.type === "atrule") {
      const atRule = node as AtRule;
      path.unshift(`@${atRule.name} ${atRule.params}`.trim());
    }
    node = node.parent;
  }
  return path.length === 0 ? "the stylesheet" : path.join(" > ");
}

/* A keyframe list declares no banned property: `@keyframes spin { to { rotate: 360deg } }` does, but
 * `@keyframes fade { to { opacity: 1 } }` is `opacity`, which is legal everywhere else. So a walk over
 * declarations reads a whole animation as legal CSS, which is what it is, one frame at a time. The at-rule
 * itself is the finding, and it is the shape stylelint refuses in source: `at-rule-disallowed-list` covers the
 * files this repository writes, and this covers the ones a dependency or a plugin emits into the artifact. */
const KEYFRAMES = /^(-\w+-)?keyframes$/;

export function checkBundle(input: CheckBundleInput): CheckOutcome {
  const findings: Finding[] = [];
  let declarations = 0;
  let atRules = 0;
  let bytes = 0;

  for (const stylesheet of input.stylesheets) {
    bytes += Buffer.byteLength(stylesheet.css);
    const root = parse(stylesheet.css, { from: stylesheet.name });

    root.walkAtRules((atRule) => {
      atRules += 1;
      if (!KEYFRAMES.test(atRule.name.trim().toLowerCase())) return;
      findings.push({
        file: stylesheet.file,
        ...(atRule.source?.start === undefined
          ? {}
          : { line: atRule.source.start.line, column: atRule.source.start.column }),
        check: "keyframes-in-the-bundle",
        message:
          `the stylesheet ships @${atRule.name} ${abbreviate(atRule.params)}, and motion is zero, ` +
          "without exception. Every frame of it is a legal declaration on its own, so the at-rule is " +
          "what has to be refused.",
      });
    });

    root.walkDecls((declaration) => {
      declarations += 1;
      const refusal = refusalFor(declaration.prop, declaration.value);
      if (refusal === null) return;
      findings.push({
        file: stylesheet.file,
        ...(declaration.source?.start === undefined
          ? {}
          : { line: declaration.source.start.line, column: declaration.source.start.column }),
        check: "banned-declaration-in-the-bundle",
        message:
          `${contextOf(declaration)} ships ${declaration.prop}: ${abbreviate(declaration.value)}, ` +
          `and ${refusal}. The bytes a browser downloads are the artifact, so no question about ` +
          "which files a check scanned can excuse this one.",
      });
    });
  }

  const barrels = checkBarrelPayloads(input.barrels);

  return {
    findings: [...findings, ...barrels.findings],
    notes: [
      `${input.stylesheets.length} built stylesheet(s), ${asKb(bytes)}`,
      `${declarations} declaration(s) read by postcss, not by a pattern`,
      `${atRules} at-rule(s) read, and a keyframe list is refused whatever it declares`,
      ...input.stylesheets.map((stylesheet) => `  ${stylesheet.name}`),
      ...barrels.notes,
    ],
  };
}

/* A composed `var(--tw-*)` chain runs to several hundred characters and says nothing a reader needs.
 * The property is the finding; the value is evidence. */
function abbreviate(value: string): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  return collapsed.length <= 96 ? collapsed : `${collapsed.slice(0, 93)}...`;
}
