/* EVERY NOTICE THE PRODUCT CAN EMIT, READ OUT OF ITS OWN SOURCE.
 *
 * The kit's `Notice` type refuses an empty `stillWorks` at compile time and the api's schema refuses one before it
 * is serialized, which between them cover every notice that crosses a boundary. What neither covers is the
 * QUESTION the audit has to answer: which notices exist at all. A reviewer asking "does every degradation notice
 * name the capability that survives it" needs the set, and a list of the notice modules written beside a test is a
 * second copy of a fact about the tree: the day a fourteenth module raises one, a list still passes while
 * describing thirteen.
 *
 * So the set is derived. Each notice is an object literal carrying a `volume` and a `stillWorks`, which is a shape
 * the TypeScript parser can find exactly and a pattern cannot: `volume:` appears in prop types, in doc comments and
 * in the kit's own type declaration, and a regex over it reports all three.
 *
 * `stillWorks` IS OFTEN A NAMED CONSTANT, because several notices in one module name the same surviving
 * capabilities and writing the list once is right. The resolution therefore follows an identifier to a
 * module-scope array in the same file, and reports anything it cannot follow as unresolved rather than as
 * satisfied: a notice whose list this cannot read is a notice the audit has not checked, and saying so is the
 * point. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import ts from "typescript";

import { appSourceDir } from "../../scripts/lib/paths.ts";

/** What the scan could establish about a notice's surviving-capability list. */
export type StillWorks = "empty" | "non-empty" | "unresolved";

export interface NoticeLiteral {
  /** Path relative to the source root, so a finding names a file a reader can open. */
  readonly file: string;
  readonly line: number;
  /** The declared volume, or null when it is not a string literal this scan can read. */
  readonly volume: string | null;
  readonly pigment: string | null;
  readonly stillWorks: StillWorks;
}

const VOLUME = "volume";
const PIGMENT = "pigment";
const STILL_WORKS = "stillWorks";

/** The generated client, which declares the wire's own notice shape and emits none. */
const GENERATED = "api/schema.d.ts";

/**
 * The module that NARROWS a wire notice into the kit's type, which is the one place a notice is built from values
 * rather than composed from words.
 *
 * Declared rather than pattern-matched, so a second module claiming the same latitude is reported. Its two
 * literals are the ones the type documents: one carries the volume the api sent, which is not a literal this scan
 * can read, and one declares a total outage, which is the single shape allowed to name nothing.
 */
export const NARROWING_MODULE = "ui/domain/notices/notice.ts";

/** This harness, which composes the finding shape below and no notice. */
const HARNESS = "testing/";

/** The string a property holds, through an `as const` if it carries one. Null for anything else. */
function stringOf(node: ts.Expression | undefined): string | null {
  if (node === undefined) return null;
  if (ts.isAsExpression(node) || ts.isParenthesizedExpression(node))
    return stringOf(node.expression);
  return ts.isStringLiteral(node) ? node.text : null;
}

/** Every module-scope `const name = [...]`, so a named capability list can be followed to its elements. */
function arrayConstants(source: ts.SourceFile): Map<string, number> {
  const found = new Map<string, number>();
  for (const statement of source.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      const initializer = declaration.initializer;
      if (!ts.isIdentifier(declaration.name) || initializer === undefined) continue;
      const array = ts.isAsExpression(initializer) ? initializer.expression : initializer;
      if (ts.isArrayLiteralExpression(array))
        found.set(declaration.name.text, array.elements.length);
    }
  }
  return found;
}

function stillWorksOf(node: ts.Expression | undefined, constants: Map<string, number>): StillWorks {
  if (node === undefined) return "unresolved";
  if (ts.isAsExpression(node) || ts.isParenthesizedExpression(node)) {
    return stillWorksOf(node.expression, constants);
  }
  if (ts.isArrayLiteralExpression(node)) {
    return node.elements.length === 0 ? "empty" : "non-empty";
  }
  if (ts.isIdentifier(node)) {
    const length = constants.get(node.text);
    if (length === undefined) return "unresolved";
    return length === 0 ? "empty" : "non-empty";
  }
  return "unresolved";
}

function propertyOf(literal: ts.ObjectLiteralExpression, name: string): ts.Expression | undefined {
  for (const property of literal.properties) {
    if (!ts.isPropertyAssignment(property)) continue;
    const key = property.name;
    const spelled = ts.isIdentifier(key) || ts.isStringLiteral(key) ? key.text : null;
    if (spelled === name) return property.initializer;
  }
  return undefined;
}

/** Every notice one module declares, which is every object literal carrying both a volume and a list. */
export function noticesIn(file: string, text: string): NoticeLiteral[] {
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const constants = arrayConstants(source);
  const found: NoticeLiteral[] = [];

  const visit = (node: ts.Node): void => {
    if (ts.isObjectLiteralExpression(node)) {
      const volume = propertyOf(node, VOLUME);
      const stillWorks = propertyOf(node, STILL_WORKS);
      if (volume !== undefined && stillWorks !== undefined) {
        found.push({
          file,
          line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
          volume: stringOf(volume),
          pigment: stringOf(propertyOf(node, PIGMENT)),
          stillWorks: stillWorksOf(stillWorks, constants),
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);

  return found;
}

/** Every notice the shipped application declares, across every module that declares one. */
export async function shippedNotices(): Promise<NoticeLiteral[]> {
  const entries = await readdir(appSourceDir, { withFileTypes: true, recursive: true });
  const files = entries
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name))
    .map((entry) => path.relative(appSourceDir, path.join(entry.parentPath, entry.name)))
    .filter((file) => !file.includes("__tests__") && !file.includes(".test."))
    .filter((file) => file !== GENERATED && !file.startsWith(HARNESS))
    .toSorted();

  const perFile = await Promise.all(
    files.map(async (file) =>
      noticesIn(file, await readFile(path.join(appSourceDir, file), "utf8")),
    ),
  );
  return perFile.flat();
}
