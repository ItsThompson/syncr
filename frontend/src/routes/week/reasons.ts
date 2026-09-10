/* SIX CLAUSE KINDS, AND THE ROW EACH ONE READS AS.
 *
 * ROWS, NEVER A PARAGRAPH. The record has a fixed schema -- at most two rejected windows, exactly one dominant term,
 * at most one superseded placement -- and rows are what say so. Composing prose from these would imply the data is
 * unbounded, which is the one thing it is not.
 *
 * THE LABELS ARE THE DESIGN RECORD'S OWN: `blocked`, `dominant`, `bound`, `floor`, `pinned`, `instead of`. They are
 * the clause kinds, lowercase, so a reader who has seen one record can read the next without learning new words.
 *
 * A CLAUSE'S VALUE IS RESOLVED, NEVER RAW. An Area id becomes a name, an instant becomes a reading in the week's own
 * zone, and a share becomes a percentage. Where an id resolves to nothing -- an Area deleted since the plan was
 * produced -- the row states the fact it has rather than a blank: a reason record outlives what it names, which is
 * exactly why it stores what it stores.
 *
 * A PINNED BLOCK'S THREE ROWS: where it now sits and when the reader put it there,
 * what the solver had chosen instead, and what that choice cost. The first two are clauses; the cost is on the
 * `instead of` clause, so the panel reads it from there rather than from a fourth clause kind that does not exist. */

import type { LabelledRow } from "../../ui/domain";
import type { WeekReadingsContext } from "./readings";
import type { components } from "../../api/schema";

type Reason = components["schemas"]["ReasonResponse"];
type Clause = components["schemas"]["ClauseResponse"];
type Block = components["schemas"]["BlockResponse"];

const PERCENT = 100;

/** Every clause of a record, in the order the record holds them, as labelled rows. */
export function reasonRowsOf(reason: Reason, context: WeekReadingsContext): LabelledRow[] {
  return reason.clauses.map((clause) => rowOf(clause, context));
}

function rowOf(clause: Clause, context: WeekReadingsContext): LabelledRow {
  switch (clause.kind) {
    case "blocked":
      return {
        label: "blocked",
        value: `${context.span(clause.window.start, clause.window.end)} · ${clause.rule}${detail(clause.detail)}`,
      };
    case "dominant":
      return { label: "dominant", value: dominantValue(clause, context) };
    case "bound":
      return {
        label: "bound",
        value: clause.cursor === null ? clause.selected : `${clause.selected} · ${clause.cursor}`,
      };
    case "floor":
      return { label: "floor", value: floorValue(clause, context) };
    case "pinned":
      return {
        label: "pinned",
        value: `${context.span(clause.at.start, clause.at.end)} · you moved it here on ${context.date(clause.pinnedOn)}`,
      };
    case "instead_of":
      return {
        label: "instead of",
        value: `${context.span(clause.placement.start, clause.placement.end)} · what the solver proposed`,
      };
  }
}

/** The dominant objective term, its share of the plan's cost, and the revision churn was measured against. */
function dominantValue(
  clause: Extract<Clause, { kind: "dominant" }>,
  context: WeekReadingsContext,
): string {
  const share = `${(clause.share * PERCENT).toFixed(0)}% of the plan's cost`;
  const baseline = clause.baseline ?? null;
  if (baseline === null) return `${clause.term} · ${share}`;
  const approved = baseline.approvedAt;
  /* A week with no approved revision reports churn as zero and states why, which is what the null pair means. */
  if (approved === null || approved === undefined) {
    return `${clause.term} · ${share} · no approved revision to measure against`;
  }
  return `${clause.term} · ${share} · against the revision approved ${context.date(approved)}`;
}

function floorValue(
  clause: Extract<Clause, { kind: "floor" }>,
  context: WeekReadingsContext,
): string {
  const name = context.areaName(clause.areaId) ?? "an Area no longer declared";
  const declaration =
    clause.declaredFloorMinutes === null
      ? "declared floor unavailable for this historical plan"
      : `declared floor ${(clause.declaredFloorMinutes / 60).toFixed(1)}h`;
  const rule = `rule floor ${(clause.floorMinutes / 60).toFixed(1)}h`;
  return `${name} ${declaration} · ${rule} · ${String(clause.placed)} of ${String(clause.of)} occurrences placed`;
}

function detail(text: string | null | undefined): string {
  return text === null || text === undefined || text === "" ? "" : ` · ${text}`;
}

/**
 * The definition rows a block's own facts read as: when, source, type, authority.
 *
 * FOUR ROWS, IN THE DESIGN RECORD'S ORDER. `when` is the placement, `source` is what produced the block, `type` is
 * the binding's kind, and `authority` is whether the product may move it: a pin is the reader's and is therefore the
 * strongest reason in the system, and a derived block is fixed without being pinned at all.
 */
export function definitionRowsOf(block: Block, context: WeekReadingsContext): LabelledRow[] {
  return [
    { label: "when", value: context.span(block.interval.start, block.interval.end) },
    { label: "source", value: block.origin },
    { label: "type", value: block.binding.kind },
    { label: "authority", value: authorityOf(block) },
  ];
}

/** What may move this block, in the words the plan-storage classifier uses for it. */
function authorityOf(block: Block): string {
  if (block.pinned) return "your own edit · the solver treats it as fixed";
  if (block.origin === "anchor") return "imported · time the product does not own";
  if (block.origin === "frame") return "derived · fixed by the circadian frame";
  return "the solver's · a re-solve may move it";
}

/** The cost of a pin, from the `instead of` clause that records it. */
export function objectiveDeltaOf(objectiveDelta: number): string {
  const sign = objectiveDelta > 0 ? "+" : "";
  return `${sign}${objectiveDelta.toFixed(2)} against the proposal`;
}
