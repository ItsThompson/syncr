import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { appSourceDir } from "../../lib/paths.ts";
import { checkChannels, variantStates } from "../check.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string): string => path.join(here, "..", "__fixtures__", name);
const themeFile = path.join(appSourceDir, "theme.css");

const check = async (names: string[]) =>
  checkChannels({ kitFiles: names.map(fixture), themeFile });

describe("one file per state channel", () => {
  it("passes when one file owns a state's channels", async () => {
    const outcome = await check(["sidebar.css"]);

    expect(outcome.findings).toEqual([]);
    expect(outcome.notes).toContain("  data-current -> fill");
    expect(outcome.notes).toContain("  data-current -> left rule");
  });

  it("fails when a second file takes the same state's fill", async () => {
    const outcome = await check(["sidebar.css", "table-row.css"]);

    expect(outcome.findings.map((finding) => finding.check)).toEqual(["one-file-per-channel"]);
    expect(outcome.findings[0].message).toContain("data-current -> fill");
    expect(outcome.findings[0].message).toContain("table-row.css");
  });

  it("does not count a property named only inside a comment", async () => {
    const outcome = await check(["table-row.css"]);

    expect(outcome.notes[0]).toContain("1 state channel(s) assigned");
  });

  it("counts a channel assigned from markup, so a variant class cannot dodge the rule", async () => {
    const outcome = await check(["Block.tsx"]);

    expect(outcome.notes).toContain("  data-conflict -> left rule");
  });

  it("fails across a stylesheet and markup alike", async () => {
    const outcome = await check(["Block.tsx", "LedgerRow.tsx"]);

    expect(outcome.findings[0].message).toContain("data-conflict -> left rule");
  });

  it("ignores a resting declaration, which is geometry rather than a channel", async () => {
    const outcome = await check(["Block.tsx"]);

    expect(outcome.notes[0]).toContain("1 state channel(s) assigned");
  });
});

describe("variantStates", () => {
  it("reads each variant's state selector from the theme, not from a second list", () => {
    const states = variantStates(
      "@custom-variant pinned (&[data-pinned]);\n@custom-variant frame (&[data-origin=\"frame\"]);",
    );

    expect(states.get("pinned")).toBe("data-pinned");
    expect(states.get("frame")).toBe("data-origin");
  });

  it("adds the pseudo-class states, which own channels but declare no variant", () => {
    const states = variantStates("");

    expect(states.get("hover")).toBe(":hover");
    expect(states.get("focus-visible")).toBe(":focus-visible");
  });
});
