/* Printing a check's outcome and turning it into an exit code.
 *
 * Every script prints its notes even when it passes. A check that silently passes cannot be
 * told apart from a check that stopped running, which is the failure mode these scripts
 * exist to prevent. */

import { type CheckOutcome, type Finding, locate } from "./findings.ts";
import { relativeToRepo } from "./paths.ts";

export function formatFinding(finding: Finding): string {
  const where = locate(relativeToRepo(finding.file), finding.line, finding.column);
  return `  ${where}\n    ${finding.check}: ${finding.message}`;
}

export function formatOutcome(title: string, outcome: CheckOutcome): string {
  const lines = [`${title}`];
  for (const note of outcome.notes) lines.push(`  ${note}`);
  if (outcome.findings.length === 0) {
    lines.push("  ok");
    return lines.join("\n");
  }
  lines.push(`  ${outcome.findings.length} problem(s):`);
  for (const finding of outcome.findings) lines.push(formatFinding(finding));
  return lines.join("\n");
}

/** Prints the outcome and returns the process exit code. */
export function reportOutcome(title: string, outcome: CheckOutcome): number {
  const text = formatOutcome(title, outcome);
  if (outcome.findings.length === 0) {
    process.stdout.write(`${text}\n`);
    return 0;
  }
  process.stderr.write(`${text}\n`);
  return 1;
}
