import { readFile } from "node:fs/promises";
import path from "node:path";

import { classStringsIn, utilitiesIn } from "../lib/class-strings.ts";
import { blankJsComments } from "../lib/comments.ts";
import { codeWithoutComments, createPositionResolver } from "../lib/css-scan.ts";
import { vocabularyOf } from "../lib/custom-variants.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { emittedDeclarationsFor } from "../lib/tailwind.ts";
import { refusedByEmittedCss } from "./emitted.ts";
import { lintSource } from "./rules.ts";

export interface LintMarkupInput {
  /** Absolute paths of the TypeScript and TSX files to check. */
  readonly sourceFiles: readonly string[];
  /**
   * Absolute paths of stylesheets to check for `@apply`. A stylesheet escaped every check before:
   * the markup scan read only `.ts` and `.tsx`, and stylelint's rules are declaration-based, so
   * `@apply blur-(--haze) shadow-(--halo) transition-(--pace)` shipped a blur, an unfenced shadow
   * and a transition-property with every check green.
   */
  readonly styleSheets: readonly string[];
  /** Absolute path of `theme.css`, which declares the closed state vocabulary and the theme. */
  readonly themeFile: string;
  /** Absolute path of the kit, inside which `rounded-*` is permitted. */
  readonly kitDir: string;
  /** Absolute path of `src/`, which the Tailwind compiler resolves the theme's imports against. */
  readonly sourceRoot: string;
}

interface UtilityUse {
  readonly utility: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
}

const APPLY_AT_RULE = /@apply\s+([^;{}]+)/g;

/* A composed `var(--tw-*)` chain runs to several hundred characters and says nothing a reader needs. */
function abbreviate(value: string): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  return collapsed.length <= 96 ? collapsed : `${collapsed.slice(0, 93)}...`;
}

/** Every utility named in an `@apply`, with the position of the directive that names it. */
async function applyUsesIn(file: string): Promise<UtilityUse[]> {
  const source = await readFile(file, "utf8");
  const at = createPositionResolver(source);
  const code = codeWithoutComments(source);
  const uses: UtilityUse[] = [];
  for (const match of code.matchAll(APPLY_AT_RULE)) {
    const position = at(match.index);
    for (const utility of utilitiesIn(match[1])) {
      uses.push({ utility, file, line: position.line, column: position.column });
    }
  }
  return uses;
}

/** Every utility named in a class string, with the position of the string that names it. */
function classUsesIn(file: string, source: string): UtilityUse[] {
  const code = blankJsComments(source);
  return classStringsIn(code).flatMap((classString) =>
    utilitiesIn(classString.text).map((utility) => ({
      utility,
      file,
      line: classString.line,
      column: classString.column,
    })),
  );
}

export async function lintMarkup(input: LintMarkupInput): Promise<CheckOutcome> {
  const themeSource = await readFile(input.themeFile, "utf8");
  const vocabulary = vocabularyOf(themeSource);
  const findings: Finding[] = [];
  const uses: UtilityUse[] = [];

  for (const file of input.sourceFiles) {
    const source = await readFile(file, "utf8");
    findings.push(
      ...lintSource({
        file,
        source,
        vocabulary,
        isKitFile: !path.relative(input.kitDir, file).startsWith(".."),
      }),
    );
    uses.push(...classUsesIn(file, source));
  }

  for (const sheet of input.styleSheets) {
    uses.push(...(await applyUsesIn(sheet)));
  }

  /* One theme compilation for the whole tree, then a verdict per utility from what it EMITS. This is
   * the half that does not depend on a pattern, so it is the half a new Tailwind spelling cannot
   * walk past. */
  const emitted = await emittedDeclarationsFor(
    input.sourceRoot,
    uses.map((use) => use.utility),
  );
  const refused = new Map(
    refusedByEmittedCss(emitted).map((verdict) => [
      verdict.utility,
      `it emits ${verdict.property}: ${abbreviate(verdict.value)}, and ${verdict.reason}`,
    ]),
  );

  for (const use of uses) {
    const reason = refused.get(use.utility);
    if (reason === undefined) continue;
    findings.push({
      file: use.file,
      line: use.line,
      column: use.column,
      check: "banned-emitted-css",
      message: `${use.utility} is refused by what it compiles to: ${reason}.`,
    });
  }

  return {
    findings: findings.toSorted((left, right) => (left.line ?? 0) - (right.line ?? 0)),
    notes: [
      `${input.sourceFiles.length} source file(s), ${input.styleSheets.length} stylesheet(s)`,
      `${new Set(uses.map((use) => use.utility)).size} distinct utilit(ies) compiled and judged by emitted CSS`,
      `closed state vocabulary: ${[...vocabulary].toSorted().join(", ")}`,
    ],
  };
}
