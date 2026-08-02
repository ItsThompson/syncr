/* The module that decides whether a gate is red.
 *
 * Three CLIs depend on `reportOutcome` returning 1 when there is a finding and 0 when there is not.
 * Everything else in this slice is enforcement, and all of it is worthless if this one mapping is
 * wrong, so it gets a standing guard rather than a reviewer's one-off probe. */

import { afterEach, describe, expect, it, vi } from "vitest";

import type { CheckOutcome, Finding } from "../findings.ts";
import { formatFinding, formatOutcome, reportOutcome } from "../report.ts";
import { repoRoot } from "../paths.ts";

const finding = (overrides: Partial<Finding> = {}): Finding => ({
  file: `${repoRoot}/frontend/src/theme.css`,
  line: 12,
  column: 3,
  check: "dangling-reference",
  message: "var(--gone) resolves to nothing.",
  ...overrides,
});

const outcome = (findings: Finding[], notes: string[] = []): CheckOutcome => ({ findings, notes });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("formatFinding", () => {
  it("locates a finding repo-relatively, so the path can be pasted into an editor", () => {
    expect(formatFinding(finding())).toContain("frontend/src/theme.css:12:3");
  });

  it("omits a column it does not have, rather than printing an empty field", () => {
    expect(formatFinding(finding({ column: undefined }))).toContain("frontend/src/theme.css:12\n");
  });

  it("omits the position entirely for a finding about a whole file", () => {
    const text = formatFinding(finding({ line: undefined, column: undefined }));
    expect(text).toContain("frontend/src/theme.css\n");
  });

  it("names the check and the message", () => {
    expect(formatFinding(finding())).toContain(
      "dangling-reference: var(--gone) resolves to nothing.",
    );
  });
});

describe("formatOutcome", () => {
  it("prints the notes on success, so a check that stopped running is not mistaken for a pass", () => {
    const text = formatOutcome("token layer", outcome([], ["5 token file(s)"]));

    expect(text).toContain("5 token file(s)");
    expect(text).toContain("ok");
  });

  it("counts the problems and lists each one", () => {
    const text = formatOutcome("token layer", outcome([finding(), finding({ line: 40 })]));

    expect(text).toContain("2 problem(s)");
    expect(text).toContain(":12:3");
    expect(text).toContain(":40:3");
  });

  it("prints the notes on failure too, so coverage is visible either way", () => {
    expect(formatOutcome("token layer", outcome([finding()], ["6 sheet(s)"]))).toContain(
      "6 sheet(s)",
    );
  });

  it("does not claim ok when there is a finding", () => {
    expect(formatOutcome("token layer", outcome([finding()]))).not.toContain("\n  ok");
  });
});

describe("reportOutcome", () => {
  it("exits 0 and writes to stdout when there is no finding", () => {
    const out = vi.spyOn(process.stdout, "write").mockReturnValue(true);
    const err = vi.spyOn(process.stderr, "write").mockReturnValue(true);

    expect(reportOutcome("token layer", outcome([]))).toBe(0);
    expect(out).toHaveBeenCalledOnce();
    expect(err).not.toHaveBeenCalled();
  });

  it("exits 1 and writes to stderr when there is one finding", () => {
    const out = vi.spyOn(process.stdout, "write").mockReturnValue(true);
    const err = vi.spyOn(process.stderr, "write").mockReturnValue(true);

    expect(reportOutcome("token layer", outcome([finding()]))).toBe(1);
    expect(err).toHaveBeenCalledOnce();
    expect(out).not.toHaveBeenCalled();
  });

  it("exits 1 for many findings too, not a count", () => {
    vi.spyOn(process.stderr, "write").mockReturnValue(true);

    expect(reportOutcome("token layer", outcome([finding(), finding(), finding()]))).toBe(1);
  });
});
