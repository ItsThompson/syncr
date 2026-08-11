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
 *   5. every `var()` reference in a reference sheet resolves against the stylesheets it LINKS
 *   6. every stylesheet reference resolves on disk, in a token file and in a sheet
 *   7. the Area ramp's hue ledger is derived from the pigments, and neither the comment beside a pigment nor a
 *      reference sheet's own copy of it may disagree
 *   8. a `@caller-provided` annotation excuses check 4 and check 5 only where a caller can reach the
 *      reference, which `scripts/validate-tokens/caller-provided.ts` settles
 *
 * Check 6 is what keeps the six sheets honest: they render live from the tokens that ship,
 * and a moved file would turn them into the second copy of the values they exist to avoid.
 * Check 7 is the same rule applied to a ledger that had already become one. */

import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  isCustomPropertyDeclaration,
  scanCss,
  type CssScan,
  type ScannedStylesheet,
} from "../lib/css-scan.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { scanHtml, type HtmlScan } from "../lib/html-scan.ts";
import type { Exists } from "../lib/module-graph.ts";
import { relativeToRepo } from "../lib/paths.ts";
import { stylesheetClosures } from "../lib/stylesheet-closure.ts";
import { callerProvidedContracts, type CallerProvidedContracts } from "./caller-provided.ts";
import { checkAreaHues, pigmentFile } from "./hues.ts";

export interface ValidateInput {
  /** Absolute paths of every file in the token layer. */
  readonly tokenFiles: readonly string[];
  /**
   * Absolute paths of stylesheets that CONSUME the layer: the theme, the base rules, and any
   * co-located component sheet. Their `var()` references must resolve, but they declare no tokens,
   * so a duplicate or a non-declaration statement in them is not this check's business.
   */
  readonly consumerFiles: readonly string[];
  /**
   * Absolute paths of every module and stylesheet the application ships, so a consumer's references can be
   * resolved against the sheets its own component actually loads rather than against every sheet in the tree.
   */
  readonly moduleFiles: readonly string[];
  /** True when a file exists at a candidate path, which is how a specifier is resolved. */
  readonly exists: Exists;
  /** Absolute path of the entry point every reference sheet must link. */
  readonly tokenEntry: string;
  /** Absolute paths of the rendered reference sheets. */
  readonly sheetFiles: readonly string[];
}

export async function validateTokenLayer(input: ValidateInput): Promise<CheckOutcome> {
  const findings: Finding[] = [];
  const scanned: ScannedStylesheet[] = [];

  for (const file of input.tokenFiles) {
    const scan = scanCss(await readFile(file, "utf8"));
    scanned.push({ file, scan });
    findings.push(...checkComments(file, scan));
    findings.push(...checkRootStatements(file, scan));
    findings.push(...checkDuplicates(file, scan));
    findings.push(...(await checkImports(file, scan)));
  }

  const declared = collectDeclaredNames(scanned);
  const contracts = callerProvidedContracts(scanned);
  findings.push(...contracts.refusals);
  findings.push(...checkTokenReferences(scanned, declared, contracts));

  /* The theme is the bridge that turns a token into a utility, so a dangling reference there
   * compiles to an invalid declaration and produces exactly the plausible-looking page this whole
   * check exists to prevent.
   *
   * A CONSUMER RESOLVES AGAINST THE TOKEN LAYER PLUS THE SHEETS ITS OWN COMPONENT LOADS, which is the cascade a
   * browser actually has. A component sheet legitimately declares layer-2 properties and legitimately reads
   * another sheet's: the kit's glyph table is declared in `ui/primitives/glyphs.css` and a domain component's key
   * hint draws its brackets from it. Resolving each sheet against itself alone reported that as dangling while
   * the browser resolves it, and resolving it against EVERY sheet in the tree passed a reference to a property
   * declared in a sheet the component never imports. `scripts/lib/stylesheet-closure.ts` walks the import graph
   * that answers it, and a sheet imported by two components is judged against the intersection of their
   * closures, because a reference has to resolve in every context the sheet is loaded in. */
  const closures = await stylesheetClosures({ files: input.moduleFiles, exists: input.exists });
  const consumerScans = new Map<string, CssScan>();
  let consumerReferences = 0;
  for (const file of input.consumerFiles) {
    const scan = scanCss(await readFile(file, "utf8"));
    consumerScans.set(file, scan);
    consumerReferences += scan.varReferences.length;
    findings.push(...checkComments(file, scan));
    findings.push(...(await checkImports(file, scan)));
  }

  let unloadedSheets = 0;
  for (const [file, scan] of consumerScans) {
    const closure = closures.get(file);
    if (closure !== undefined && closure.importers.length === 0) unloadedSheets += 1;
    const visible = new Set(declared);
    for (const loaded of closure?.loadedWith ?? [file]) {
      for (const declaration of consumerScans.get(loaded)?.declarations ?? []) {
        visible.add(declaration.name);
      }
    }
    findings.push(...checkTokenReferences([{ file, scan }], visible, contracts));
  }

  let dynamicInSheets = 0;
  let resolvedInSheets = 0;
  let promotedInSheets = 0;
  for (const file of input.sheetFiles) {
    const scan = scanHtml(await readFile(file, "utf8"));
    dynamicInSheets += scan.dynamicVarReferences.length;
    resolvedInSheets += scan.varReferences.length;
    const linked = namesLinkedBy(file, scan, consumerScans);
    promotedInSheets += linked.size;
    findings.push(...checkSheetReferences(file, scan, declared, contracts.honored, linked));
    findings.push(...(await checkSheetLink(file, scan, input.tokenEntry)));
  }

  const notes = [
    `${input.tokenFiles.length} token file(s), ${declared.size} declared propert(ies)`,
    `${input.consumerFiles.length} consuming stylesheet(s), ${consumerReferences} var() reference(s) resolved`,
    `  each against the token layer plus the sheets its own component loads`,
    `  ${unloadedSheets} sheet(s) no module imports, which resolve against the token layer alone`,
    `${input.sheetFiles.length} reference sheet(s), ${resolvedInSheets} literal var() reference(s) resolved`,
    `  each against the token layer plus the component sheets the sheet itself links`,
    `  ${promotedInSheets} propert(ies) reached that way, which is where a promoted layer-2 token lives`,
    `${dynamicInSheets} var() reference(s) in the sheets are assembled at runtime and are not statically resolvable`,
  ];
  if (contracts.honored.size > 0) {
    notes.push(`caller-provided by contract: ${[...contracts.honored].toSorted().join(", ")}`);
  }

  const ramp = await checkAreaHues({ pigmentFile, sheetFiles: input.sheetFiles });
  findings.push(...ramp.findings);
  notes.push(...ramp.notes);

  return { findings, notes };
}

function collectDeclaredNames(scanned: readonly ScannedStylesheet[]): Set<string> {
  const names = new Set<string>();
  for (const { scan } of scanned) {
    for (const declaration of scan.declarations) names.add(declaration.name);
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
    // A bare specifier like `tailwindcss` is resolved from node_modules by the bundler, not from
    // this directory. Only a path this file claims to own is checkable here.
    if (!atImport.specifier.startsWith(".") && !atImport.specifier.startsWith("/")) continue;
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
  scanned: readonly ScannedStylesheet[],
  declared: ReadonlySet<string>,
  contracts: CallerProvidedContracts,
): Finding[] {
  const findings: Finding[] = [];
  for (const { file, scan } of scanned) {
    for (const reference of scan.varReferences) {
      if (declared.has(reference.name) || contracts.honored.has(reference.name)) continue;
      findings.push({
        file,
        line: reference.line,
        column: reference.column,
        check: "dangling-reference",
        message:
          `var(${reference.name}) resolves to nothing. ` +
          remedyFor(reference.name, contracts.refused.has(reference.name)),
      });
    }
  }
  return findings;
}

/* A name whose annotation was refused in this same run must not be sent back to the annotation: the
 * advice would re-create the defect the refusal just reported. */
function remedyFor(name: string, wasRefused: boolean): string {
  if (wasRefused) {
    return (
      `Declare it, or move the reference onto the rule that paints. The "@caller-provided ${name}" ` +
      "annotation cannot excuse it here."
    );
  }
  return (
    `Declare it, or annotate the contract with "@caller-provided ${name}" in a comment where the ` +
    "caller's formula is stated."
  );
}

/* THE PROPERTIES A SHEET REACHES THROUGH ITS OWN `<link>` TAGS, following each linked sheet's `@import` chain.
 *
 * A reference sheet renders live from what ships, and what ships is not all in `tokens/`: section 14's promotion
 * table moves a component's own geometry down to a layer-2 sheet beside the component when that component is
 * built. Resolving a sheet's references against the token directory alone therefore refuses every legitimate
 * promotion, which made the interim location a rule rather than the interim measure the table calls it.
 *
 * The honesty guarantee is unchanged and is what picks this over an allowlist: a name resolves only if the sheet
 * LINKS the file that declares it, so the browser has the value on the same load the check approved. */
function namesLinkedBy(
  file: string,
  scan: HtmlScan,
  scans: ReadonlyMap<string, CssScan>,
): Set<string> {
  const names = new Set<string>();
  const seen = new Set<string>();
  const pending = scan.stylesheetLinks
    .filter((link) => !/^[a-z]+:/i.test(link.href))
    .map((link) => path.resolve(path.dirname(file), link.href));

  while (pending.length > 0) {
    const sheet = pending.pop();
    if (sheet === undefined || seen.has(sheet)) continue;
    seen.add(sheet);
    const linked = scans.get(sheet);
    if (linked === undefined) continue;
    for (const declaration of linked.declarations) names.add(declaration.name);
    for (const atImport of linked.imports) {
      if (!atImport.specifier.startsWith(".")) continue;
      pending.push(path.resolve(path.dirname(sheet), atImport.specifier));
    }
  }
  return names;
}

function checkSheetReferences(
  file: string,
  scan: HtmlScan,
  declared: ReadonlySet<string>,
  callerProvided: ReadonlySet<string>,
  linked: ReadonlySet<string>,
): Finding[] {
  const findings: Finding[] = [];
  for (const reference of scan.varReferences) {
    if (declared.has(reference.name)) continue;
    if (callerProvided.has(reference.name)) continue;
    if (scan.declaredNames.has(reference.name)) continue;
    if (linked.has(reference.name)) continue;
    findings.push({
      file,
      line: reference.line,
      column: reference.column,
      check: "dangling-sheet-reference",
      message:
        `var(${reference.name}) resolves against none of the token files, the stylesheets this ` +
        "sheet links, or its own declarations, so the sheet renders a missing value and still " +
        "looks plausible.",
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
      message: `links no stylesheet resolving to ${relativeToRepo(tokenEntry)}, so it can drift from the build.`,
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
