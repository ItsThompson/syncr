/* One finding shape and one report format for every committed check, so a failure reads
 * the same whether it came from the token validator, the markup scan or the channel
 * assertion. */

export interface Finding {
  /** Absolute path of the file the finding is about. */
  readonly file: string;
  /** 1-based. Absent when the finding is about the file as a whole. */
  readonly line?: number;
  /** 1-based. Absent when the finding is about a whole line. */
  readonly column?: number;
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
