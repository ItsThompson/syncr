/* A single-pass scanner over CSS text.
 *
 * It is deliberately not a full CSS parser. A parser recovers from a broken comment the way
 * a browser does, which is exactly the behaviour being guarded against: the browser
 * discards every declaration after the break and renders something plausible. This scanner
 * reports the break instead.
 *
 * The pass produces a `code` projection in which every comment is replaced by spaces of the
 * same length, so byte offsets stay aligned with the original text and every position
 * reported downstream points at the real source. */

export interface Position {
  readonly line: number;
  readonly column: number;
}

export interface Declaration extends Position {
  readonly name: string;
  readonly value: string;
}

export interface Statement extends Position {
  readonly text: string;
}

export interface VarReference extends Position {
  readonly name: string;
}

export interface AtImport extends Position {
  readonly specifier: string;
}

export interface CommentProblem extends Position {
  readonly message: string;
}

export interface CallerProvided extends Position {
  readonly name: string;
}

export interface CssScan {
  readonly declarations: readonly Declaration[];
  readonly rootStatements: readonly Statement[];
  readonly varReferences: readonly VarReference[];
  /** A `var()` whose argument is assembled at runtime, so it cannot be resolved statically. */
  readonly dynamicVarReferences: readonly Position[];
  readonly commentProblems: readonly CommentProblem[];
  readonly imports: readonly AtImport[];
  readonly callerProvided: readonly CallerProvided[];
}

const CUSTOM_PROPERTY = "--[A-Za-z0-9_-]+";
const DECLARATION_PATTERN = new RegExp(`(${CUSTOM_PROPERTY})\\s*:`, "g");
const VAR_PATTERN = new RegExp(`\\bvar\\(\\s*(${CUSTOM_PROPERTY})?`, "g");
const IMPORT_PATTERN = /@import\s+(?:url\(\s*)?["']([^"']+)["']/g;
const CALLER_PROVIDED_PATTERN = new RegExp(`@caller-provided\\s+(${CUSTOM_PROPERTY})`, "g");
const ROOT_SELECTOR_PATTERN = /(^|[\s,}])(:root)\s*\{/g;

/** Maps a byte offset onto a 1-based line and column. */
export function createPositionResolver(text: string): (offset: number) => Position {
  const lineStarts = [0];
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\n") lineStarts.push(index + 1);
  }
  return (offset) => {
    let low = 0;
    let high = lineStarts.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (lineStarts[middle] <= offset) low = middle;
      else high = middle - 1;
    }
    return { line: low + 1, column: offset - lineStarts[low] + 1 };
  };
}

interface CommentPass {
  readonly code: string;
  readonly commentText: readonly { readonly text: string; readonly offset: number }[];
  readonly problems: readonly CommentProblem[];
}

/** Blanks every comment, and reports an opener with no closer or a closer with no opener. */
function stripComments(text: string, at: (offset: number) => Position): CommentPass {
  const code: string[] = [];
  const commentText: { text: string; offset: number }[] = [];
  const problems: CommentProblem[] = [];
  let index = 0;
  let quote: string | null = null;

  while (index < text.length) {
    const character = text[index];

    if (quote !== null) {
      if (character === "\\") {
        code.push(text.slice(index, index + 2));
        index += 2;
        continue;
      }
      // A CSS string cannot span a line. Ending it at the newline is what the browser's own
      // tokenizer does, and it is load-bearing here: a stray apostrophe in a paragraph of
      // prose would otherwise swallow the rest of the file, including the very comment
      // marker the paragraph is missing.
      if (character === quote || character === "\n") quote = null;
      code.push(character);
      index += 1;
      continue;
    }

    if (character === '"' || character === "'") {
      quote = character;
      code.push(character);
      index += 1;
      continue;
    }

    if (character === "*" && text[index + 1] === "/") {
      problems.push({
        ...at(index),
        message:
          "a comment closer with no opener. Every declaration after it is discarded by the " +
          "browser, which then renders a plausible page with missing values.",
      });
      code.push("  ");
      index += 2;
      continue;
    }

    if (character === "/" && text[index + 1] === "*") {
      const end = text.indexOf("*/", index + 2);
      if (end === -1) {
        problems.push({
          ...at(index),
          message:
            "an unterminated comment. Everything after it is swallowed, so every token " +
            "declared below silently resolves to nothing.",
        });
        commentText.push({ text: text.slice(index + 2), offset: index + 2 });
        code.push(" ".repeat(text.length - index));
        break;
      }
      commentText.push({ text: text.slice(index + 2, end), offset: index + 2 });
      const blanked = text.slice(index, end + 2).replace(/[^\n]/g, " ");
      code.push(blanked);
      index = end + 2;
      continue;
    }

    code.push(character);
    index += 1;
  }

  return { code: code.join(""), commentText, problems };
}

/** Splits a block body into statements on `;` at paren depth zero. */
function splitStatements(body: string, offset: number, at: (o: number) => Position): Statement[] {
  const statements: Statement[] = [];
  let depth = 0;
  let start = 0;

  const push = (from: number, to: number): void => {
    const raw = body.slice(from, to);
    if (raw.trim() === "") return;
    const leading = raw.length - raw.trimStart().length;
    statements.push({ ...at(offset + from + leading), text: raw.trim() });
  };

  for (let index = 0; index < body.length; index += 1) {
    const character = body[index];
    if (character === "(") depth += 1;
    else if (character === ")") depth = Math.max(0, depth - 1);
    else if (character === ";" && depth === 0) {
      push(start, index);
      start = index + 1;
    }
  }
  push(start, body.length);
  return statements;
}

/** Returns the offset just past the `}` that closes the block opening at `openBrace`. */
function findBlockEnd(code: string, openBrace: number): number {
  let depth = 0;
  for (let index = openBrace; index < code.length; index += 1) {
    if (code[index] === "{") depth += 1;
    else if (code[index] === "}") {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return code.length;
}

export function scanCss(text: string): CssScan {
  const at = createPositionResolver(text);
  const { code, commentText, problems } = stripComments(text, at);

  const declarations: Declaration[] = [];
  for (const match of code.matchAll(DECLARATION_PATTERN)) {
    const start = match.index + match[0].length;
    const end = findValueEnd(code, start);
    declarations.push({ ...at(match.index), name: match[1], value: code.slice(start, end).trim() });
  }

  const rootStatements: Statement[] = [];
  for (const match of code.matchAll(ROOT_SELECTOR_PATTERN)) {
    const openBrace = match.index + match[0].length - 1;
    const closeBrace = findBlockEnd(code, openBrace);
    rootStatements.push(
      ...splitStatements(code.slice(openBrace + 1, closeBrace), openBrace + 1, at),
    );
  }

  const varReferences: VarReference[] = [];
  const dynamicVarReferences: Position[] = [];
  for (const match of code.matchAll(VAR_PATTERN)) {
    if (match[1] === undefined) dynamicVarReferences.push(at(match.index));
    else varReferences.push({ ...at(match.index), name: match[1] });
  }

  const imports: AtImport[] = [];
  for (const match of code.matchAll(IMPORT_PATTERN)) {
    imports.push({ ...at(match.index), specifier: match[1] });
  }

  const callerProvided: CallerProvided[] = [];
  for (const comment of commentText) {
    for (const match of comment.text.matchAll(CALLER_PROVIDED_PATTERN)) {
      callerProvided.push({ ...at(comment.offset + match.index), name: match[1] });
    }
  }

  return {
    declarations,
    rootStatements,
    varReferences,
    dynamicVarReferences,
    commentProblems: problems,
    imports,
    callerProvided,
  };
}

/** The text with every comment replaced by spaces, so offsets still line up with the source. */
export function codeWithoutComments(text: string): string {
  return stripComments(text, createPositionResolver(text)).code;
}

function findValueEnd(code: string, start: number): number {
  let depth = 0;
  for (let index = start; index < code.length; index += 1) {
    const character = code[index];
    if (character === "(") depth += 1;
    else if (character === ")") depth = Math.max(0, depth - 1);
    else if ((character === ";" || character === "}") && depth === 0) return index;
  }
  return code.length;
}

/** True when a `:root` statement is a real custom-property declaration. */
export function isCustomPropertyDeclaration(statement: string): boolean {
  return new RegExp(`^${CUSTOM_PROPERTY}\\s*:\\s*\\S`).test(statement);
}
