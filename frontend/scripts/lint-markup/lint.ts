import { readFile } from "node:fs/promises";
import path from "node:path";

import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { vocabularyOf } from "../lib/custom-variants.ts";
import { lintSource } from "./rules.ts";

export interface LintMarkupInput {
  /** Absolute paths of the TypeScript and TSX files to check. */
  readonly sourceFiles: readonly string[];
  /** Absolute path of `theme.css`, which declares the closed state vocabulary. */
  readonly themeFile: string;
  /** Absolute path of the kit, inside which `rounded-*` is permitted. */
  readonly kitDir: string;
}

export async function lintMarkup(input: LintMarkupInput): Promise<CheckOutcome> {
  const vocabulary = vocabularyOf(await readFile(input.themeFile, "utf8"));
  const findings: Finding[] = [];

  for (const file of input.sourceFiles) {
    findings.push(
      ...lintSource({
        file,
        source: await readFile(file, "utf8"),
        vocabulary,
        isKitFile: !path.relative(input.kitDir, file).startsWith(".."),
      }),
    );
  }

  return {
    findings,
    notes: [
      `${input.sourceFiles.length} source file(s)`,
      `closed state vocabulary: ${[...vocabulary].toSorted().join(", ")}`,
    ],
  };
}
