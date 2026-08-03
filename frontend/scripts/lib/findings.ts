/* One finding shape and one report format for every committed check, so a failure reads
 * the same whether it came from the token validator, the markup scan, the channel
 * assertion or the zone probe.
 *
 * Optional fields are declared `?: T | undefined` throughout this codebase rather than `?: T`.
 * Under `exactOptionalPropertyTypes` the bare form forbids passing an absent value through, and
 * the workaround is a spread-to-omit at every call site. */

export interface Finding {
  /** Absolute path of the file the finding is about. */
  readonly file: string;
  /** 1-based. Absent when the finding is about the file as a whole. */
  readonly line?: number | undefined;
  /** 1-based. Absent when the finding is about a whole line. */
  readonly column?: number | undefined;
  /** The rule that produced the finding, as a short stable identifier. */
  readonly check: string;
  readonly message: string;
}

export interface CheckOutcome {
  readonly findings: readonly Finding[];
  /** Lines printed on success as well as failure, so coverage is visible either way. */
  readonly notes: readonly string[];
}

export function locate(file: string, line?: number, column?: number): string {
  return [file, line, column].filter((part) => part !== undefined).join(":");
}

/**
 * A value quoted inside a message, collapsed onto one line and cut short.
 *
 * A composed `var(--tw-*)` chain runs to several hundred characters and a hoisted class expression can run to
 * several lines. Neither says anything a reader needs past the first clause, and a finding that wraps four
 * times buries the position it is pointing at.
 */
export function abbreviate(value: string, limit = 96): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  return collapsed.length <= limit ? collapsed : `${collapsed.slice(0, limit - 3)}...`;
}
