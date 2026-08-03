/* THE INLINE-STYLE SCANNER, ON ITS OWN.
 *
 * `__tests__/lint.test.ts` drives it through the whole markup check against a fixture file, which is the
 * right level for "does this rule fire". These cases are about the SCANNER: which keys and values it reads
 * out of an object literal, and which shapes it must not misread. That is where its defects have been, both
 * of them found by a fixture rather than by inspection: keys compared in CSS spelling while React writes
 * camelCase, and a value compared with its quotes still on. */

import { describe, expect, it } from "vitest";

import { createPositionResolver } from "../../lib/css-scan.ts";
import { inlineStyleFindings } from "../inline-style.ts";

function scan(code: string, file = "/src/ui/domain/week/Block.tsx") {
  return inlineStyleFindings({ file, code, at: createPositionResolver(code) });
}

const checksOf = (code: string) => scan(code).map((finding) => finding.check);

describe("the properties an inline style may not set", () => {
  it("reads a camelCase key as the declaration React writes", () => {
    const findings = scan(`<div style={{ backdropFilter: "blur(4px)" }} />`);

    expect(findings.map((finding) => finding.check)).toEqual(["no-banned-property-in-style"]);
    expect(findings[0].message).toContain("backdrop-filter");
  });

  it('reads a quoted value as the value, so outline: "none" is outline: none', () => {
    const findings = scan(`<div style={{ outline: "none" }} />`);

    expect(findings.map((finding) => finding.check)).toEqual(["no-banned-property-in-style"]);
    expect(findings[0].message).toContain("keyboard-first");
  });

  it("reads a quoted key, which is how a vendor-prefixed property has to be written", () => {
    expect(checksOf(`<div style={{ "-webkit-filter": "blur(2px)" }} />`)).toEqual([
      "no-banned-property-in-style",
    ]);
  });

  it("reads every key in the object rather than stopping at the first", () => {
    expect(
      checksOf(`<div style={{ height: gridHeight, willChange: "transform", scale: "1.02" }} />`),
    ).toEqual(["no-banned-property-in-style", "no-banned-property-in-style"]);
  });

  it("leaves a computed length and a custom property alone, which the week grid needs", () => {
    expect(checksOf(`<div style={{ height: \`\${minutes}px\`, "--ai": area.ink }} />`)).toEqual([]);
  });
});

describe("the values an inline style may not carry", () => {
  it("refuses a raw colour whatever property carries it", () => {
    expect(checksOf(`<div style={{ borderColor: "#16307F" }} />`)).toEqual([
      "no-raw-value-in-style",
    ]);
  });

  it("refuses a radius, because a class list and an inline style are one rule", () => {
    expect(checksOf(`<div style={{ borderRadius: "8px" }} />`)).toEqual(["no-radius-in-style"]);
  });

  it("permits a square radius, which is what the token resolves to", () => {
    expect(checksOf(`<div style={{ borderRadius: "var(--radius)" }} />`)).toEqual([]);
  });

  it("permits a circle in one of the four files the design language names", () => {
    const inside = scan(`<span style={{ borderRadius: "50%" }} />`, "/src/ui/domain/StatusDot.tsx");
    const elsewhere = scan(`<span style={{ borderRadius: "50%" }} />`, "/src/ui/domain/Chip.tsx");

    expect(inside).toEqual([]);
    expect(elsewhere.map((finding) => finding.check)).toEqual(["no-radius-in-style"]);
  });
});

describe("shapes the scanner must not misread", () => {
  /* A colon inside a ternary or a string is not a declaration. The fail-safe direction is to yield a key the
   * shared list does not know, which is why the colour patterns run over the object's whole text as well. */
  it("takes no key out of a ternary in a value", () => {
    expect(checksOf(`<div style={{ height: isOpen ? "40px" : "0px" }} />`)).toEqual([]);
  });

  it("takes no key out of a string that contains a colon", () => {
    expect(checksOf(`<div style={{ background: "url(https://x/y.png)" }} />`)).toEqual([]);
  });

  it("still sees a banned property after a value holding braces", () => {
    expect(
      checksOf(
        `<div style={{ gridTemplate: \`\${rows.map((r) => r).join(" ")}\`, rotate: "3deg" }} />`,
      ),
    ).toEqual(["no-banned-property-in-style"]);
  });

  it("finds every style prop in a file, not only the first", () => {
    expect(
      checksOf(`<div style={{ transition: "none 0s" }} /><p style={{ scale: "2" }} />`),
    ).toEqual(["no-banned-property-in-style", "no-banned-property-in-style"]);
  });

  it("points at the style prop that carries the offence", () => {
    const findings = scan(`<div\n  className="p-2"\n  style={{ rotate: "3deg" }}\n/>`);

    expect(findings[0].line).toBe(3);
  });
});
