/* The Today screen's state, its writes, and the keys that reach them.
 *
 * THE ROUTE IS COMPOSITION AND THIS IS THE BEHAVIOUR. Everything that is not "where does this sit on the
 * page" lives here: the two reads, the two pieces of state, the six bare keys, and the three writes.
 *
 * ONE OPEN FORM, AND ONE CURRENT ROW. A row claims the cursor as focus enters its controls and releases it as
 * focus leaves. `j` and `k` also move it without moving DOM focus, so a reader can choose a row before they
 * record its exception. The row takes the kit's `data-current` state; this screen owns only which row is current.
 *
 * A KEY WITH NO CURRENT ROW DOES NOTHING, deliberately. The alternative is defaulting to a row the reader was
 * not looking at, and skipping the wrong block is a correction they have to notice before they can make it.
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
import { useCalendarSources } from "../../../api/hooks/useCalendarSources";
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
import type { WireNotice } from "../../../ui/domain";
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
  /** The row the cursor marks, or null before a row has been chosen. */
  readonly currentBlockId: string | null;
  readonly actions: RowActions;
  /** The last refused recording and the row it belongs to. */
  readonly rowRefusal: OutcomeRefusal | null;
  /** The last refused confirmation of the day. */
  readonly confirmationRefusal: Problem | null;
  /**
   * The notices the api composed about this tenant's sources, or none while the read has not arrived.
   *
   * NOT PART OF THE READING, deliberately. A day whose commitments came from a feed reads identically whether
   * that feed is answering or not, and the notice that says otherwise is composed on the api -- staleness is
   * never computed here. But the ledger's whole job is answering for blocks, and a source read that failed to
   * arrive must not take the rows off the screen. So this read degrades to silence rather than to a failure
   * surface.
   */
  readonly sourceNotices: readonly WireNotice[];
  /** What the last backfill settled. */
  readonly settled: Backfill | null;
  readonly onConfirm: () => void;
  readonly onBackfill: () => void;
}

/* A stable empty list, so a render before the source read arrives does not hand the screen a fresh array every time. */
const NO_SOURCE_NOTICES: readonly WireNotice[] = [];

export function useTodayLedger(): TodayLedger {
  const [date] = useState(() => hostDateOf(new Date()));
  const [form, setForm] = useState<OutcomeForm | null>(null);
  const [currentBlockId, setCurrentBlockId] = useState<string | null>(null);

  const day = useDay(date);
  const areas = useAreas();
  const sources = useCalendarSources();

  const held = day.status === "ready" ? day.data : null;
  const rows = held === null ? [] : [...held.behind, ...held.ahead];
  const current = rows.find((row) => row.blockId === currentBlockId) ?? null;
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
    rows.find((row) => row.blockId === blockId);

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
    onEnter: (row) => setCurrentBlockId(row.blockId),
    onLeave: () => setCurrentBlockId(null),
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

  const moveCurrent = (direction: 1 | -1): void => {
    if (rows.length === 0) return;

    const currentIndex = rows.findIndex((row) => row.blockId === currentBlockId);
    if (currentIndex === -1) {
      setCurrentBlockId(rows.at(direction === 1 ? 0 : -1)?.blockId ?? null);
      return;
    }

    const nextIndex = Math.max(0, Math.min(rows.length - 1, currentIndex + direction));
    setCurrentBlockId(rows[nextIndex]?.blockId ?? null);
  };

  useKeyBinding({ key: "j" }, () => moveCurrent(1));
  useKeyBinding({ key: "k" }, () => moveCurrent(-1));
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
    currentBlockId: current?.blockId ?? null,
    actions,
    rowRefusal: recording.refusal,
    confirmationRefusal: confirmation.problem,
    sourceNotices: sources.status === "ready" ? sources.data.notices : NO_SOURCE_NOTICES,
    settled: backfill.settled,
    onConfirm: confirm,
    onBackfill: () => void backfill.submit(backfillRange(date)),
  };
}
