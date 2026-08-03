/* WHICH OF THE GLYPH SLOT'S FOUR OCCUPANTS WINS IT.
 *
 * The slot is one small space and four kinds of mark can claim it. The precedence is settled by the design
 * language rather than by this file, and it is stated here once so the week grid and a ledger row cannot
 * answer it differently:
 *
 *   pinned          wins over everything. A pin is the user's own edit and the strongest reason in the system
 *   overlap count   wins over the proposal source. A hidden block is a legibility problem, and a proposal
 *                   already has the fill channel saying what it is
 *   proposal source wins over the origin mark, which is the only one that is merely provenance
 *   origin          the mark a block falls back to when its title no longer fits
 *
 * WHICH TIER SHOWS WHICH MARK IS NOT DECIDED HERE. The origin mark appears below the label tiers and the other
 * three appear at them, and a tier is the grid's geometry: the caller passes the origin only where it has room
 * for nothing else, and passes a count only where the grid has staggered blocks behind this one. Reading a
 * tier here would put the grid's geometry in a mark. */

/** What kind of intent produced a block. The domain's seven, in the domain's own spelling. */
export type BlockOrigin =
  "frame" | "template_entry" | "habit" | "task" | "anchor" | "prep" | "transit";

/** The mark that ends up in the slot, or null when nothing claims it. */
export type GlyphSlotOccupant = BlockOrigin | "pinned" | "overlap" | "proposal-source";

export interface GlyphSlotClaim {
  /** The user's own edit. */
  readonly isPinned?: boolean | undefined;
  /** This block comes from the pending proposal rather than from the live plan. */
  readonly isProposalSource?: boolean | undefined;
  /**
   * How many blocks are staggered behind this one, where the grid has decided to say so.
   *
   * The marker appears at depth 4 and above, so a count of one or none is not a claim on the slot: passing one
   * would put the digit `1` where an origin mark belongs, and the grid's own threshold is the caller's.
   */
  readonly overlapCount?: number | undefined;
  /** The origin mark, passed only at a tier with no room for a title. */
  readonly origin?: BlockOrigin | undefined;
}

export function glyphSlotOccupant(claim: GlyphSlotClaim): GlyphSlotOccupant | null {
  if (claim.isPinned === true) return "pinned";
  if (claim.overlapCount !== undefined && claim.overlapCount > 1) return "overlap";
  if (claim.isProposalSource === true) return "proposal-source";
  return claim.origin ?? null;
}
