/* Comment blanking, which is what lets the markup rules read code rather than prose. */

import { describe, expect, it } from "vitest";

import { blankJsComments } from "../comments.ts";

describe("blankJsComments", () => {
  it("blanks a line comment and keeps every offset", () => {
    const source = 'const a = 1; // data-busy here\nconst b = "keep";';
    const blanked = blankJsComments(source);

    expect(blanked).toHaveLength(source.length);
    expect(blanked).not.toContain("data-busy");
    expect(blanked).toContain('const b = "keep";');
  });

  it("blanks a block comment while preserving its newlines, so line numbers hold", () => {
    const source = "/* one\n   two data-busy */\nconst a = 1;";
    const blanked = blankJsComments(source);

    expect(blanked.split("\n")).toHaveLength(3);
    expect(blanked).not.toContain("data-busy");
    expect(blanked.split("\n")[2]).toBe("const a = 1;");
  });

  it("keeps a comment marker that is inside a string, which is what a URL looks like", () => {
    const source = 'const url = "https://example.com/a"; const b = 2;';

    expect(blankJsComments(source)).toBe(source);
  });

  it("keeps a block-comment opener inside a string", () => {
    const source = 'const pattern = "/* not a comment */"; const b = 2;';

    expect(blankJsComments(source)).toBe(source);
  });

  it("spans lines for a template literal but not for a plain string", () => {
    const template = "const a = `one\ntwo`; // gone";
    expect(blankJsComments(template)).toContain("two`;");
    expect(blankJsComments(template)).not.toContain("gone");

    // An unterminated plain string ends at the newline, as the language's own tokenizer does, so a
    // stray quote cannot swallow the rest of the file.
    const unterminated = 'const a = "oops\nconst b = 1; // gone';
    expect(blankJsComments(unterminated)).not.toContain("gone");
    expect(blankJsComments(unterminated)).toContain("const b = 1;");
  });

  it("blanks an unterminated block comment to the end of the file", () => {
    const source = "const a = 1;\n/* never closed data-busy";

    expect(blankJsComments(source)).not.toContain("data-busy");
    expect(blankJsComments(source)).toContain("const a = 1;");
  });

  it("keeps an escaped quote from ending a string early", () => {
    const source = 'const a = "he said \\"hi\\" loudly"; // gone';
    const blanked = blankJsComments(source);

    expect(blanked).toContain('loudly"');
    expect(blanked).not.toContain("gone");
  });
});
