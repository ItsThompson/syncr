/* Formatting is gated so twenty tickets of TypeScript do not accumulate drift that review has to
 * carry. The settings match what the tree was already written in rather than imposing a new taste:
 * 100 columns, matching ruff's line-length for the Python members, double quotes, and trailing
 * commas.
 *
 * Prettier does not reflow comment prose, so the wrapped rationale comments throughout this
 * codebase survive it unchanged. */

export default {
  printWidth: 100,
  singleQuote: false,
  trailingComma: "all",
  arrowParens: "always",
  semi: true,
};
