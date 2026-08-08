/* The same settings the frontend is formatted with, restated here rather than imported, because the two
 * trees have separate dependency closures and a config imported across them would make this package's
 * formatting depend on the other one being installed.
 *
 * 100 columns, matching ruff's line-length for the Python members. Prettier does not reflow comment
 * prose, so the wrapped rationale comments throughout this harness survive it unchanged. */

export default {
  printWidth: 100,
  singleQuote: false,
  trailingComma: "all",
  arrowParens: "always",
  semi: true,
};
