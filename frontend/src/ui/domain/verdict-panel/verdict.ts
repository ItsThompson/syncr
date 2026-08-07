/* WHAT THE VERDICT PANEL RENDERS, IN THE KIT'S OWN TERMS.
 *
 * The kit does not know what a response is, so a verdict arrives here already resolved: an Area id has become an
 * Area's name, an instant has become a reading in the reader's own zone, and a concession has become the sentence
 * the api wrote for it. The route does that narrowing, which is the same boundary `GridBlock` sits on.
 *
 * PROVENANCE IS A FIELD, NOT A TONE. `probe` is a capacity check, which proves impossibility and never possibility,
 * and `solver` is an attempted placement. The panel states which, because a product that asserted something it did
 * not compute would be worse than one that says less.
 *
 * A CONCESSION IS NOT A SHORTFALL and they are two lists for that reason. A week that has absorbed a concession must
 * not read as simply feasible, so the concessions are listed ABOVE the gaps: otherwise the product reports a healthy
 * week for a reason the reader cannot see. */

/** Whether the verdict came from the capacity probe or from an attempted placement. */
export type VerdictProvenance = "probe" | "solver";

/** Which check produced a gap. The api's own four, in its spelling. */
export type ShortfallKind =
  | "floors_exceed_capacity"
  | "deadline_capacity"
  | "area_floor_unreachable"
  | "minimum_chunk_unplaceable";

/** The four concessions the panel may offer, in the api's spelling. */
export type TradeoffKind = "drop_item" | "reduce_routine" | "breach_floor" | "accept_partial";

/** One quantified gap, with everything a reader needs to act on it already in words. */
export interface VerdictShortfall {
  readonly id: string;
  readonly kind: ShortfallKind;
  /** `1h20m`, already formatted, because how a duration reads is one decision for the whole screen. */
  readonly shortfall: string;
  /** What cannot be satisfied, in the user's own words for it. */
  readonly against: readonly string[];
  /** The constraints respected while computing the gap, so the number is not the only thing said. */
  readonly honoring: readonly string[];
  /** The deadline the gap is measured against, as a reading, or null where none applies. */
  readonly deadline: string | null;
}

/** One concession the panel offers. Requesting it mutates nothing. */
export interface VerdictTradeoff {
  readonly kind: TradeoffKind;
  /** The api's own wording: it is per kind and per target, and names the nights a reduction would touch. */
  readonly label: string;
  readonly targetId: string;
  /** What approving it would recover, already formatted, or null where the enumerator could not size it. */
  readonly recovers: string | null;
}

/** One concession this week has already absorbed. */
export interface VerdictConcession {
  readonly id: string;
  readonly label: string;
  /** When it was approved, as a reading, or null. */
  readonly approvedOn: string | null;
}

export interface PanelVerdict {
  readonly provenance: VerdictProvenance;
  /** True only from an attempted placement: arithmetic cannot prove a week works. */
  readonly isFeasible: boolean;
  /** Whether the check found no gap. Weaker than feasible. */
  readonly capacityIsSufficient: boolean;
  readonly shortfalls: readonly VerdictShortfall[];
  readonly tradeoffs: readonly VerdictTradeoff[];
}

const MINUTES_IN_HOUR = 60;

/** `1h20m`, `45m`, `2h`. The one spelling of a duration on this screen. */
export function formatMinutes(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes));
  const hours = Math.floor(whole / MINUTES_IN_HOUR);
  const rest = whole % MINUTES_IN_HOUR;
  if (hours === 0) return `${String(rest)}m`;
  if (rest === 0) return `${String(hours)}h`;
  return `${String(hours)}h${String(rest)}m`;
}

/** What the panel calls the evidence: a capacity check, or the authoritative reading. */
export function provenanceReading(provenance: VerdictProvenance): string {
  return provenance === "probe" ? "capacity check" : "authoritative";
}

/**
 * The panel's lead sentence.
 *
 * NO VERDICT CLAIMS A WEEK IS FEASIBLE ON PROBE EVIDENCE ALONE, which is why a clean probe reads as a check that
 * found nothing rather than as a week that holds. The three sentences are the three things that can honestly be
 * said.
 */
export function verdictHeadline(verdict: PanelVerdict, concessionCount: number): string {
  if (verdict.shortfalls.length > 0) return "This week cannot hold its commitments";
  if (verdict.provenance === "probe") return "No shortfall found in this week's capacity";
  if (concessionCount > 0) return concessionSentence(concessionCount);
  return "This week holds its commitments";
}

function concessionSentence(count: number): string {
  return count === 1
    ? "This week holds, with one concession"
    : `This week holds, with ${String(count)} concessions`;
}

/** The strip's own second line: the first gap, in the verdict's own words, or what stands instead. */
export function verdictDetail(verdict: PanelVerdict): string {
  const first = verdict.shortfalls.at(0);
  if (first === undefined) return `${provenanceReading(verdict.provenance)} · no gap`;
  const against = first.against.join(", ");
  const deadline = first.deadline === null ? "" : ` before ${first.deadline}`;
  return `${first.shortfall} short on ${against}${deadline}`;
}
