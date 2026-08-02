import { describe, expect, it } from "vitest";

import { isCustomPropertyDeclaration, scanCss } from "../css-scan.ts";

describe("scanCss", () => {
  it("keeps a multi-line value with nested parentheses as one declaration", () => {
    const scan = scanCss(`:root {
  --hatch-cross:
    repeating-linear-gradient(45deg,  var(--hatch-ink) 0 1px, transparent 1px 6px),
    repeating-linear-gradient(135deg, var(--hatch-ink) 0 1px, transparent 1px 6px);
  --hatch-mix: 45%;
}`);
    expect(scan.declarations.map((declaration) => declaration.name)).toEqual([
      "--hatch-cross",
      "--hatch-mix",
    ]);
    expect(scan.rootStatements).toHaveLength(2);
  });

  it("reads every :root block in a file", () => {
    const scan = scanCss(":root { --a: 1px; }\n.x { color: red }\n:root { --b: 2px; }");
    expect(scan.rootStatements.map((statement) => statement.text)).toEqual([
      "--a: 1px",
      "--b: 2px",
    ]);
  });

  it("ignores a declaration-shaped string inside a comment", () => {
    const scan = scanCss(
      ":root {\n  /* a caller writes --hatch-ink: var(--rule) */\n  --a: 1px;\n}",
    );
    expect(scan.declarations.map((declaration) => declaration.name)).toEqual(["--a"]);
    expect(scan.varReferences).toEqual([]);
  });

  it("reports positions against the original text, comments included", () => {
    const scan = scanCss("/* one\n   two */\n:root {\n  --a: var(--b);\n}");
    expect(scan.varReferences[0]).toMatchObject({ name: "--b", line: 4, column: 8 });
  });

  it("separates a var() built at runtime from one it can resolve", () => {
    const scan = scanCss(":root { --a: var(--b); --c: var(); }");
    expect(scan.varReferences.map((reference) => reference.name)).toEqual(["--b"]);
    expect(scan.dynamicVarReferences).toHaveLength(1);
  });

  it("does not let an apostrophe in prose swallow the rest of the file", () => {
    const scan = scanCss(":root {\n  a block's height is proportional\n  --a: 1px;\n}");
    expect(scan.declarations.map((declaration) => declaration.name)).toEqual(["--a"]);
    expect(scan.rootStatements[0].text).toContain("block's height");
  });

  it("records @import targets in source order", () => {
    const scan = scanCss("@import './primitives.css';\n@import url(\"./color.css\");");
    expect(scan.imports.map((atImport) => atImport.specifier)).toEqual([
      "./primitives.css",
      "./color.css",
    ]);
  });

  it("reads a caller-provided annotation out of a comment", () => {
    const scan = scanCss(
      "/* @caller-provided --hatch-ink\n   the drawing element owns it */\n:root {}",
    );
    expect(scan.callerProvided.map((annotation) => annotation.name)).toEqual(["--hatch-ink"]);
  });
});

describe("isCustomPropertyDeclaration", () => {
  it.each([
    ["--a: 1px", true],
    ["--block-h-label:19px", true],
    ["--a:", false],
    ["color: red", false],
    ["THE LABEL TIER LADDER", false],
    ["-a: 1px", false],
  ])("%s -> %s", (statement, expected) => {
    expect(isCustomPropertyDeclaration(statement)).toBe(expected);
  });
});
