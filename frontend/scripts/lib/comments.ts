/* Blanking comments in TypeScript source, so a check reads code rather than prose.
 *
 * This is the same discipline `css-scan.ts` applies to stylesheets and `custom-variants.ts` applies
 * to the theme, and the markup rules need it for the same reason: a rule sensitive enough to catch
 * `<span data-busy>` is also sensitive enough to catch the words "the data-attribute variant" in a
 * sentence explaining the rule. A check that fails on the comment documenting it is a check people
 * learn to route around.
 *
 * Comments are replaced by spaces of the same length, newlines preserved, so every offset still
 * points at the real source and a reported line and column stay correct. */

const QUOTES = new Set(['"', "'", "`"]);

export function blankJsComments(source: string): string {
  const out: string[] = [];
  let index = 0;
  let quote: string | null = null;

  while (index < source.length) {
    const character = source[index];

    if (quote !== null) {
      if (character === "\\") {
        out.push(source.slice(index, index + 2));
        index += 2;
        continue;
      }
      // A template literal may span lines; a plain string may not, and ending it at the newline is
      // what the language's own tokenizer does.
      if (character === quote || (quote !== "`" && character === "\n")) quote = null;
      out.push(character);
      index += 1;
      continue;
    }

    if (QUOTES.has(character)) {
      quote = character;
      out.push(character);
      index += 1;
      continue;
    }

    if (character === "/" && source[index + 1] === "/") {
      const end = source.indexOf("\n", index);
      const stop = end === -1 ? source.length : end;
      out.push(" ".repeat(stop - index));
      index = stop;
      continue;
    }

    if (character === "/" && source[index + 1] === "*") {
      const end = source.indexOf("*/", index + 2);
      const stop = end === -1 ? source.length : end + 2;
      out.push(source.slice(index, stop).replace(/[^\n]/g, " "));
      index = stop;
      continue;
    }

    out.push(character);
    index += 1;
  }

  return out.join("");
}
