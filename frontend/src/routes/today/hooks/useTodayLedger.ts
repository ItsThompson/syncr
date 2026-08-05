/* The Today screen's state, its writes, and the keys that reach them.
 *
 * THE ROUTE IS COMPOSITION AND THIS IS THE BEHAVIOUR. Everything that is not "where does this sit on the
 * page" lives here: the two reads, the two pieces of state, the four bare keys, and the three writes.
 *
 * ONE OPEN FORM, AND THE ROW A KEY ACTS ON IS THE FOCUSED ONE. A ledger has no cursor: the design language
 * gives a row no channel for one, and inventing a focus ring outside the kit would be a second definition of
 * a state the kit already assigns. So the row a bare keystroke lands on is the row whose controls hold
 * focus, claimed as focus enters the row and RELEASED AS FOCUS LEAVES IT. The release is half of the rule
 * rather than tidiness: without it the row a key acts on is the last row focus ever entered, which never
 * expires, so a keystroke meant for nothing would skip a block the reader had moved away from.
 *
 * A KEY WITH NO FOCUSED ROW DOES NOTHING, deliberately. The alternative is defaulting to a row the reader was
 * not looking at, and skipping the wrong block is a correction they have to notice before they can make it.
 * The premise panel states which row the keys act on.
 *
 * `c` APPLIES THE RULE ITS OWN BUTTON APPLIES. Confirming a day with no block stores nothing and confirming
 * one that has not been read cannot know what it is answering for, and both bump the solve-input version of
 * this week and every later one, so the key is guarded on the same condition that disables the control.
 *
 * THE CLOCK IS READ DURING RENDER, and the review's suggestion to pin it at mount is declined for one
 * reason: `dayStanding` compares it against the day's own span, and that comparison is the only thing that
 * tells a reader a tab left open past midnight is showing yesterday. A frozen clock would never make it.
 * Keying it to the day's arrival instead is what the hook lint refuses, because a memo whose callback does
 * not read its dependency is not a memo. Two renders of one commit can differ by a second, which a displayed
 * clock and a span comparison both absorb. */

import { useState } from "react";

import { useKeyBinding } from "../../../lib/keyboard";
import { useAreas, type Areas } from "../../../api/hooks/useAreas";
import {
  useBackfill,
  useDay,
  useDayConfirmation,
  useOutcomeRecording,
  type Backfill,
  type Day,
  type DayRow,
  type OutcomeBody,
  type OutcomeRefusal,
} from "../../../api/hooks/useDay";
import { readingOf, type Reading } from "../../reading";
import { backfillRange } from "../backfill";
import { bodyFor, movedFormFor, partialFormFor, stateBody } from "../drafts";
import { hostDateOf } from "../instants";
import { isoWeekOf } from "../isoWeek";
import type { Problem } from "../../../contract";
import type { OutcomeForm, RowActions } from "../types";

/**
 * The two reads this screen needs before it can draw a row.
 *
 * A `type` rather than an `interface`, because the reading helper takes a record of named resources and an
 * interface carries no index signature: the shape has to be assignable where it crosses that boundary.
 */
export type LedgerReads = {
  day: Day;
  Areas: Areas;
};

export interface TodayLedger {
  /** The date the ledger is addressed by, held still while the screen is open. */
  readonly date: string;
  /** The instant the screen was drawn at, which is what the day's own span is compared against. */
  readonly nowIso: string;
  readonly reading: Reading<LedgerReads>;
  /** The form open on one row, or null when none is. */
  readonly form: OutcomeForm | null;
  readonly actions: RowActions;
  /** The last refused recording and the row it belongs to. */
  readonly rowRefusal: OutcomeRefusal | null;
  /** The last refused confirmation of the day. */
  readonly confirmationRefusal: Problem | null;
  /** What the last backfill settled. */
  readonly settled: Backfill | null;
  readonly onConfirm: () => void;
  readonly onBackfill: () => void;
}

export function useTodayLedger(): TodayLedger {
  const [date] = useState(() => hostDateOf(new Date()));
  const [form, setForm] = useState<OutcomeForm | null>(null);
  const [current, setCurrent] = useState<DayRow | null>(null);

  const day = useDay(date);
  const areas = useAreas();

  const held = day.status === "ready" ? day.data : null;
  const recording = useOutcomeRecording(date, held);
  const confirmation = useDayConfirmation(date, held);
  const backfill = useBackfill(date);

  const isoWeek = isoWeekOf(date);
  const nowIso = new Date().toISOString();

  const record = (row: DayRow, body: OutcomeBody | null): void => {
    setForm(null);
    if (body === null) return;
    void recording.record({ blockId: row.blockId, outcome: body });
  };

  const rowOf = (blockId: string): DayRow | undefined =>
    held === null
      ? undefined
      : [...held.behind, ...held.ahead].find((row) => row.blockId === blockId);

  const actions: RowActions = {
    onSkip: (row) => record(row, stateBody("skipped", isoWeek)),
    onPresume: (row) => record(row, stateBody("presumed", isoWeek)),
    onPartial: (row) => setForm(partialFormFor(row)),
    /* The zone is the day's, never a default: `instants.ts` resolves a wall time against it, and a
     * fallback would resolve one in a zone the reader is not in. No row exists before the day does. */
    onMoved: (row) => {
      if (held !== null) setForm(movedFormFor(row, held.zone));
    },
    onDraft: setForm,
    onCancel: () => setForm(null),
    onEnter: setCurrent,
    onLeave: () => setCurrent(null),
    onRecord: () => {
      if (form === null || held === null) return;
      const row = rowOf(form.blockId);
      if (row === undefined) return;
      record(row, bodyFor(form, { date, zone: held.zone, isoWeek }));
    },
  };

  const confirm = (): void => {
    if (held === null || held.blockCount === 0) return;
    void confirmation.submit();
  };

  useKeyBinding({ key: "x" }, () => {
    if (current !== null) actions.onSkip(current);
  });
  /* `Shift+X` arrives as the capital, which is why this is a second binding rather than a modifier flag. */
  useKeyBinding({ key: "X" }, () => {
    if (current !== null) actions.onPartial(current);
  });
  useKeyBinding({ key: "m" }, () => {
    if (current !== null) actions.onMoved(current);
  });
  useKeyBinding({ key: "c" }, confirm);

  return {
    date,
    nowIso,
    reading: readingOf<LedgerReads>({ day, Areas: areas }),
    form,
    actions,
    rowRefusal: recording.refusal,
    confirmationRefusal: confirmation.problem,
    settled: backfill.settled,
    onConfirm: confirm,
    onBackfill: () => void backfill.submit(backfillRange(date)),
  };
}
