/* The token file validator.
 *
 * A broken comment in a token file is a silent, TOTAL failure. A prose paragraph left
 * outside a comment pair is a CSS parse error and the browser discards every declaration
 * after it. That happened once during design: `--block-h-label` resolved to nothing, every
 * block computed as a sliver, and the six reference sheets rendered a plausible-looking week
 * grid with no titles at all. Nothing about the output said anything was wrong.
 *
 * So the layer is checked mechanically rather than read:
 *
 *   1. comments are balanced
 *   2. every statement inside `:root` is a real custom-property declaration
 *   3. no property is declared twice in one file
 *   4. every `var()` reference in a token file resolves
 *   5. every `var()` reference in a reference sheet resolves against the token files
 *   6. every stylesheet reference resolves on disk, in a token file and in a sheet
 *
 * Check 6 is what keeps the six sheets honest: they render live from the tokens that ship,
 * and a moved file would turn them into the second copy of the values they exist to avoid. */

import { readFile } from "node:fs/promises";
import path from "node:path";

import { isCustomPropertyDeclaration, scanCss, type CssScan } from "../lib/css-scan.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { scanHtml, type HtmlScan } from "../lib/html-scan.ts";

export interface ValidateInput {
  /** Absolute paths of every file in the token layer. */
  readonly tokenFiles: readonly string[];
  /** Absolute path of the entry point every reference sheet must link. */
  readonly tokenEntry: string;
  /** Absolute paths of the rendered reference sheets. */
  readonly sheetFiles: readonly string[];
}

interface ScannedFile {
  readonly file: string;
  readonly scan: CssScan;
}

export async function validateTokenLayer(input: ValidateInput): Promise<CheckOutcome> {
  const findings: Finding[] = [];
  const scanned: ScannedFile[] = [];

  for (const file of input.tokenFiles) {
    const scan = scanCss(await readFile(file, "utf8"));
    scanned.push({ file, scan });
    findings.push(...checkComments(file, scan));
    findings.push(...checkRootStatements(file, scan));
    findings.push(...checkDuplicates(file, scan));
    findings.push(...(await checkImports(file, scan)));
  }

  const declared = collectDeclaredNames(scanned);
  const callerProvided = collectCallerProvided(scanned);
  findings.push(...checkTokenReferences(scanned, declared, callerProvided));

  let dynamicInSheets = 0;
  let resolvedInSheets = 0;
  for (const file of input.sheetFiles) {
    const scan = scanHtml(await readFile(file, "utf8"));
    dynamicInSheets += scan.dynamicVarReferences.length;
    resolvedInSheets += scan.varReferences.length;
    findings.push(...checkSheetReferences(file, scan, declared, callerProvided));
    findings.push(...(await checkSheetLink(file, scan, input.tokenEntry)));
  }

  const notes = [
    `${input.tokenFiles.length} token file(s), ${declared.size} declared propert(ies)`,
    `${input.sheetFiles.length} reference sheet(s), ${resolvedInSheets} literal var() reference(s) resolved`,
    `${dynamicInSheets} var() reference(s) in the sheets are assembled at runtime and are not statically resolvable`,
  ];
  if (callerProvided.size > 0) {
    notes.push(`caller-provided by contract: ${[...callerProvided].toSorted().join(", ")}`);
  }

  return { findings, notes };
}

function collectDeclaredNames(scanned: readonly ScannedFile[]): Set<string> {
  const names = new Set<string>();
  for (const { scan } of scanned) {
    for (const declaration of scan.declarations) names.add(declaration.name);
  }
  return names;
}

/* A property the token layer REFERENCES but deliberately does not declare, because the
 * element that draws with it supplies the value. The contract is annotated in the token file
 * that consumes it, next to the formula a caller writes, rather than in an allowlist inside
 * this script where nobody reading the token would find it. */
function collectCallerProvided(scanned: readonly ScannedFile[]): Set<string> {
  const names = new Set<string>();
  for (const { scan } of scanned) {
    for (const annotation of scan.callerProvided) names.add(annotation.name);
  }
  return names;
}

function checkComments(file: string, scan: CssScan): Finding[] {
  return scan.commentProblems.map((problem) => ({
    file,
    line: problem.line,
    column: problem.column,
    check: "comment-balance",
    message: problem.message,
  }));
}

function checkRootStatements(file: string, scan: CssScan): Finding[] {
  return scan.rootStatements
    .filter((statement) => !isCustomPropertyDeclaration(statement.text))
    .map((statement) => ({
      file,
      line: statement.line,
      column: statement.column,
      check: "root-statement",
      message:
        "not a custom-property declaration: " +
        `${JSON.stringify(truncate(statement.text))}. Prose or a typo inside :root parses ` +
        "as nothing and takes the rest of the block with it.",
    }));
}

function checkDuplicates(file: string, scan: CssScan): Finding[] {
  const seen = new Map<string, number>();
  const findings: Finding[] = [];
  for (const declaration of scan.declarations) {
    const first = seen.get(declaration.name);
    if (first === undefined) {
      seen.set(declaration.name, declaration.line);
      continue;
    }
    findings.push({
      file,
      line: declaration.line,
      column: declaration.column,
      check: "duplicate-property",
      message: `${declaration.name} is already declared on line ${first}. The later one wins silently.`,
    });
  }
  return findings;
}

async function checkImports(file: string, scan: CssScan): Promise<Finding[]> {
  const findings: Finding[] = [];
  for (const atImport of scan.imports) {
    const target = path.resolve(path.dirname(file), atImport.specifier);
    if (await isReadable(target)) continue;
    findings.push({
      file,
      line: atImport.line,
      column: atImport.column,
      check: "stylesheet-reference",
      message: `@import "${atImport.specifier}" does not resolve. The whole imported layer is missing.`,
    });
  }
  return findings;
}

function checkTokenReferences(
  scanned: readonly ScannedFile[],
  declared: ReadonlySet<string>,
  callerProvided: ReadonlySet<string>,
): Finding[] {
  const findings: Finding[] = [];
  for (const { file, scan } of scanned) {
    for (const reference of scan.varReferences) {
      if (declared.has(reference.name) || callerProvided.has(reference.name)) continue;
      findings.push({
        file,
        line: reference.line,
        column: reference.column,
        check: "dangling-reference",
        message:
          `var(${reference.name}) resolves to nothing. Declare it, or annotate the contract ` +
          `with "@caller-provided ${reference.name}" in a comment where the caller's formula is stated.`,
      });
    }
  }
  return findings;
}

function checkSheetReferences(
  file: string,
  scan: HtmlScan,
  declared: ReadonlySet<string>,
  callerProvided: ReadonlySet<string>,
): Finding[] {
  const findings: Finding[] = [];
  for (const reference of scan.varReferences) {
    if (declared.has(reference.name)) continue;
    if (callerProvided.has(reference.name)) continue;
    if (scan.declaredNames.has(reference.name)) continue;
    findings.push({
      file,
      line: reference.line,
      column: reference.column,
      check: "dangling-sheet-reference",
      message:
        `var(${reference.name}) resolves against neither the token files nor this sheet's own ` +
        "declarations, so the sheet renders a missing value and still looks plausible.",
    });
  }
  return findings;
}

async function checkSheetLink(
  file: string,
  scan: HtmlScan,
  tokenEntry: string,
): Promise<Finding[]> {
  const local = scan.stylesheetLinks.filter((link) => !/^[a-z]+:/i.test(link.href));
  if (local.length === 0) {
    return [
      {
        file,
        check: "stylesheet-reference",
        message:
          "links no local stylesheet. A reference sheet must link the token entry point so it " +
          "renders from the values that ship.",
      },
    ];
  }

  const findings: Finding[] = [];
  let linksTokenEntry = false;
  for (const link of local) {
    const target = path.resolve(path.dirname(file), link.href);
    if (target === tokenEntry) linksTokenEntry = true;
    if (await isReadable(target)) continue;
    findings.push({
      file,
      line: link.line,
      column: link.column,
      check: "stylesheet-reference",
      message: `href="${link.href}" does not resolve.`,
    });
  }
  if (!linksTokenEntry) {
    findings.push({
      file,
      check: "stylesheet-reference",
      message: `links no stylesheet resolving to ${tokenEntry}, so it can drift from the build.`,
    });
  }
  return findings;
}

async function isReadable(target: string): Promise<boolean> {
  try {
    await readFile(target);
    return true;
  } catch {
    return false;
  }
}

function truncate(text: string): string {
  const collapsed = text.replace(/\s+/g, " ");
  return collapsed.length <= 70 ? collapsed : `${collapsed.slice(0, 67)}...`;
}
