/* `/today`: the ledger. Did this happen, and one keystroke to say the day is answered for.
 *
 * A LEDGER RATHER THAN A ONE-COLUMN GRID. The Week screen is proportional because a reader drags in it; this
 * screen answers a different question, so it is a checklist in time order and it earns the density a table
 * gives.
 *
 * COMPOSITION ONLY. The state, the writes and the keys are `useTodayLedger`'s; what is here is which surface
 * each reading draws and where the two runs of rows sit.
 *
 * THE READS BELONG TO THE ROUTE AND EVERY COMPONENT BELOW TAKES ITS DATA AS PROPS. Two reads: the day, which
 * is the ledger, and the Areas, which is where a chip's assigned pigment comes from. The wire carries an
 * Area's id and name on a row and not its pigment, so the pair is joined here rather than by a row that
 * fetched.
 *
 * NO VARIANT LABEL IS RENDERED BESIDE A BLOCK. The rotation cursor is derived from the outcome log on one
 * seam and expanded against an empty log on another, so today the two can disagree. Every title on this
 * screen is the plan of record's own, read from one source, so this screen makes no claim that could. */

import { EmptyState, ErrorState, PendingState, areaPigment, type Notice } from "../../ui/domain";
import type { AreaPigment } from "../../ui/domain";
import type { Areas } from "../../api/hooks/useAreas";
import type { Day } from "../../api/hooks/useDay";
import { RouteBand } from "../RouteBand";
import { CheckOffPremise } from "./components/CheckOffPremise";
import { DayBand } from "./components/DayBand";
import { LedgerSection } from "./components/LedgerSection";
import { useTodayLedger, type TodayLedger } from "./hooks/useTodayLedger";
import { AHEAD_TITLE, BEHIND_TITLE, backfillReading, bandReading, dayStanding } from "./labels";
import {
  backfillSettledNotice,
  confirmationRefusedNotice,
  recordingRefusedNotice,
  unconfirmedNotice,
} from "./notices";

/** The ramp step each Area holds, so a chip is drawn with the pigment the domain assigned it. */
function pigmentsOf(areas: Areas): ReadonlyMap<string, AreaPigment> {
  return new Map(areas.areas.map((area) => [area.id, areaPigment(area.pigmentIndex)]));
}

/**
 * Every notice the DAY carries, in the order a reader meets them.
 *
 * The unconfirmed one is informational and the other two are amber and verdigris, which is the shell's own
 * table: an unconfirmed day is the ordinary state of a day until the evening pass.
 */
function dayNotices(day: Day, ledger: TodayLedger): Notice[] {
  const notices: Notice[] = [];
  if (day.confirmedAt === null && day.blockCount > 0) {
    notices.push(unconfirmedNotice(day.date, day.unconfirmedDays));
  }
  if (ledger.confirmationRefusal !== null) {
    notices.push(confirmationRefusedNotice(day.date, ledger.confirmationRefusal));
  }
  if (ledger.settled !== null) {
    notices.push(
      backfillSettledNotice(
        day.date,
        backfillReading(ledger.settled.confirmedDays, ledger.settled.blocksRecorded),
        ledger.settled.unconfirmedDays,
      ),
    );
  }
  return notices;
}

/** The refused recording, paired with the row it belongs to so one row renders it. */
function rowRefusalOf(ledger: TodayLedger): { blockId: string; notice: Notice } | null {
  if (ledger.rowRefusal === null) return null;
  return {
    blockId: ledger.rowRefusal.blockId,
    notice: recordingRefusedNotice(ledger.rowRefusal.blockId, ledger.rowRefusal.problem),
  };
}

export function TodayRoute() {
  const ledger = useTodayLedger();
  const { reading } = ledger;

  if (reading.status === "loading") {
    return (
      <RouteBand title="Today" sub="the ledger">
        <PendingState
          title="Reading today"
          detail="The day's blocks in time order, and what the log says happened to each."
        />
      </RouteBand>
    );
  }
  if (reading.status === "error") {
    return (
      <RouteBand title="Today" sub="the ledger">
        <ErrorState
          title={`The ${reading.name} could not be read`}
          detail={reading.problem.detail}
        />
      </RouteBand>
    );
  }

  const { day, Areas: areas } = reading.data;
  const pigments = pigmentsOf(areas);
  const refusal = rowRefusalOf(ledger);
  const standing = dayStanding(day, ledger.nowIso);

  return (
    <RouteBand title="Today" sub={bandReading(day, ledger.nowIso)}>
      <div className="flex flex-col gap-3.25">
        <DayBand
          day={day}
          notices={dayNotices(day, ledger)}
          onConfirm={ledger.onConfirm}
          onBackfill={ledger.onBackfill}
        />
        {standing === null ? null : <p className="text-eyebrow text-text-muted">{standing}</p>}
        {day.blockCount === 0 ? (
          <EmptyState
            title="No blocks are planned for this day"
            detail={
              "There is nothing to answer for: either this day's week holds no plan yet, or the plan " +
              "put nothing in it. A day holding no block is never counted among the unconfirmed ones."
            }
          />
        ) : (
          <>
            <LedgerSection
              title={BEHIND_TITLE}
              section="behind"
              rows={day.behind}
              zone={day.zone}
              pigments={pigments}
              emptyStatement="No block of this day has ended yet."
              form={ledger.form}
              refusal={refusal}
              actions={ledger.actions}
              footer={areas.ramp.statement ?? undefined}
            />
            <LedgerSection
              title={AHEAD_TITLE}
              section="ahead"
              rows={day.ahead}
              zone={day.zone}
              pigments={pigments}
              emptyStatement="Every block of this day has ended."
              form={ledger.form}
              refusal={refusal}
              actions={ledger.actions}
            />
          </>
        )}
        <CheckOffPremise />
      </div>
    </RouteBand>
  );
}
