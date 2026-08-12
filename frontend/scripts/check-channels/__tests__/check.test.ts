import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { appSourceDir } from "../../lib/paths.ts";
import { UNCHANNELLED, unchannelledReason } from "../channels.ts";
import { checkChannels, variantStates } from "../check.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string): string => path.join(here, "..", "__fixtures__", name);
const themeFile = path.join(appSourceDir, "theme.css");

const check = async (names: string[]) => checkChannels({ kitFiles: names.map(fixture), themeFile });

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

/* The two channels section 14 names that the script did not cover until iteration 3. Tickets 8 and
 * 35 assign them first, so they are the next two that would have drifted unseen. */
describe("the glyph slot and the quarter-line weight", () => {
  it("sees the glyph slot as a channel", async () => {
    const outcome = await check(["pinned-glyph.css"]);

    expect(outcome.notes).toContain("  data-pinned -> glyph slot");
    expect(outcome.findings).toEqual([]);
  });

  it("fails when a second file claims the same state's glyph slot", async () => {
    const outcome = await check(["pinned-glyph.css", "pinned-glyph-again.css"]);

    expect(outcome.findings.map((finding) => finding.check)).toEqual(["one-file-per-channel"]);
    expect(outcome.findings[0].message).toContain("data-pinned -> glyph slot");
  });

  /* THE WAY THIS KIT ACTUALLY ASSIGNS IT. `glyphs.css` states `content: var(--glyph)` once, on the slot, and
   * a state switches the MARK by setting that property. Reading only `content` reported the glyph slot as
   * unassigned while a state was driving it, so the script agreed with a claim the kit could
   * not support. */
  it("sees a state that switches the mark through --glyph rather than through content", async () => {
    const outcome = await check(["glyph-property.css"]);

    expect(outcome.notes).toContain("  data-state -> glyph slot");
    expect(outcome.findings).toEqual([]);
  });

  it("fails when a second file switches the same state's mark", async () => {
    const outcome = await check(["glyph-property.css", "glyph-property-again.css"]);

    expect(outcome.findings.map((finding) => finding.check)).toEqual(["one-file-per-channel"]);
    expect(outcome.findings[0].message).toContain("data-state -> glyph slot");
  });

  it("sees the quarter-line weight, which is the drag state on the grid", async () => {
    const outcome = await check(["drag-weight.css"]);

    expect(outcome.notes).toContain("  data-dragging -> quarter-line weight");
  });
});

/* THE ONE CHANNEL WHOSE RESTING VALUE IS INVISIBILITY.
 *
 * A control seen only while focused has no resting mark to compare against, so it spends the clip geometry
 * rather than a colour. The properties it spends are geometry under every other state, which is why the
 * entry is scoped and why the scoping needs an arm of its own: widened, it would read a hovered row's own
 * box as a reveal, and removed, the reveal itself becomes five properties the model is silent about. */
describe("hidden until focused", () => {
  it("reads the reveal as one channel, on the focus state", async () => {
    const outcome = await check(["focus-reveal.css"]);

    expect(outcome.findings).toEqual([]);
    expect(outcome.notes).toContain("  :focus-visible -> hidden until focused");
  });

  it("names all six properties the treatment spends, so a missing one is a finding", async () => {
    const outcome = await check(["focus-reveal.css"]);

    expect(outcome.notes[1]).toContain("6 declaration(s) carry one");
  });

  it("fails when a second file reveals a control under the same state", async () => {
    const outcome = await check(["focus-reveal.css", "focus-reveal-again.css"]);

    expect(outcome.findings.map((finding) => finding.check)).toEqual(["one-file-per-channel"]);
    expect(outcome.findings[0].message).toContain(":focus-visible -> hidden until focused");
    expect(outcome.findings[0].message).toContain("focus-reveal-again.css");
  });

  it("leaves the same properties to geometry under any other state", async () => {
    const outcome = await check(["reveal-outside-focus.css"]);

    expect(outcome.findings.map((finding) => finding.message.split(", which")[0])).toEqual([
      ":hover spends width",
      ":hover spends height",
      ":hover spends overflow",
      ":hover spends clip-path",
      ":hover spends margin",
    ]);
  });

  /* The exclusion's other edge. `position` is named as carrying no channel for any state, and a
   * state-specific channel is consulted first, so the reveal takes it under focus while every other state
   * still routes through the exemption rather than through this channel. */
  it("leaves position to the exemption outside the focus state", async () => {
    const outcome = await check(["reveal-outside-focus.css"]);

    expect(outcome.notes[1]).toContain("1 named as carrying none");
    expect(outcome.notes[0]).toContain("0 state channel(s) assigned");
  });

  /* THE MARKUP SPELLING OF THE SAME TREATMENT. `sr-only` and its inverse are the two utilities that carry
   * the whole of it, so a variant-prefixed one is an assignment like any other. Without them in the model
   * the markup form would be skipped in silence: only a CSS declaration reaches the unmodelled report, so
   * an unnamed utility is neither counted nor refused. The bare `sr-only` in the same class string records
   * nothing, which is what keeps the permanently-hidden sites out of this channel. */
  it("counts the reveal written as a variant utility, so markup cannot dodge the pair rule", async () => {
    const outcome = await check(["FocusReveal.tsx"]);

    expect(outcome.notes).toContain("  :focus-visible -> hidden until focused");
    expect(outcome.notes[1]).toContain("1 declaration(s) carry one");
  });

  it("fails when a stylesheet and a class string both reveal a control", async () => {
    const outcome = await check(["focus-reveal.css", "FocusReveal.tsx"]);

    expect(outcome.findings.map((finding) => finding.check)).toEqual(["one-file-per-channel"]);
    expect(outcome.findings[0].message).toContain(":focus-visible -> hidden until focused");
    expect(outcome.findings[0].message).toContain("FocusReveal.tsx");
  });
});

/* A PROPERTY THE MODEL DOES NOT NAME WAS UNSEEN RATHER THAN UNASSIGNED.
 *
 * `channelFor` returns null for a property in no channel, and the caller skipped it, so a state could spend
 * one with every check green: the review put `color` and `letter-spacing` back onto the current row and this
 * script, the combination matrix and the layer rules all passed. Modelling text colour as a channel was the
 * other candidate fix and was rejected, because three control families legitimately mute their own label and
 * the pair rule would report all three as drift. So the model names what carries no channel instead, and its
 * silence is the finding. */
describe("a property no channel names", () => {
  it("is reported, naming the state and the property", async () => {
    const outcome = await check(["unmodelled-property.css"]);
    const unmodelled = outcome.findings.filter((finding) => finding.check === "unmodelled-channel");

    expect(unmodelled.map((finding) => finding.message.split(", which")[0])).toEqual([
      "data-current spends color",
      "data-current spends letter-spacing",
    ]);
  });

  it("says what to do about it, in the words the model uses", async () => {
    const outcome = await check(["unmodelled-property.css"]);
    const first = outcome.findings.find((finding) => finding.check === "unmodelled-channel");

    expect(first?.message).toContain("UNSEEN");
    expect(first?.message).toContain("CHANNELS");
    expect(first?.message).toContain("UNCHANNELLED");
  });

  it("points at the declaration rather than at the rule", async () => {
    const outcome = await check(["unmodelled-property.css"]);
    const letterSpacing = outcome.findings.find((finding) =>
      finding.message.includes("letter-spacing"),
    );

    expect(letterSpacing?.line).toBe(12);
  });

  it("leaves the two channels the row does spend alone", async () => {
    const outcome = await check(["unmodelled-property.css"]);

    expect(outcome.notes).toContain("  data-current -> fill");
    expect(outcome.notes).toContain("  data-current -> left rule");
  });

  it("permits the properties the model names as carrying none", async () => {
    const outcome = await check(["unchannelled-by-name.css"]);

    expect(outcome.findings).toEqual([]);
  });

  it("grants text ink to a control family and not to a row, which is where it was a defect", () => {
    expect(unchannelledReason("color", "data-disabled")).toContain("control family");
    expect(unchannelledReason("color", "data-current")).toBeNull();
  });

  it("states a reason for every exemption, so silence cannot arrive as a list entry", () => {
    for (const entry of UNCHANNELLED) expect(entry.reason.length).toBeGreaterThan(20);
  });
});

describe("variantStates", () => {
  it("reads each variant's state selector from the theme, not from a second list", () => {
    const states = variantStates(
      '@custom-variant pinned (&[data-pinned]);\n@custom-variant frame (&[data-origin="frame"]);',
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
