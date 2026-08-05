/* The day's own figures and the two acts that belong to the day rather than to a row.
 *
 * FOUR FIGURES, EACH SERVER-COMPUTED. The block count and the presumed count come from the day read, and so
 * does the count of unconfirmed days: the Week screen renders the same figure from its own week read, and
 * both come from one rule in the api so the two surfaces cannot disagree about the same week. Counting the
 * rows here would be a second rule.
 *
 * CONFIRMING ANSWERS FOR THE WHOLE DAY, INCLUDING THE BLOCKS STILL AHEAD IN IT, which is what the control
 * says. A day's last block routinely ends on the next day, so a rule that waited for every block to end
 * would leave today unconfirmable until tomorrow morning for every reader who sleeps.
 *
 * THE BACKFILL CONTROL STATES HOW MANY DAYS IT WOULD SETTLE, and it is absent when that figure is zero: a
 * control offering to confirm nothing is a control with nothing to do. */

import { Button } from "../../../ui/primitives";
import { KeyHint, NoticeCard, type Notice } from "../../../ui/domain";
import { StatCell, Strip } from "../../../ui/layout";
import type { Day } from "../../../api/hooks/useDay";
import { backfillLabel, confirmationReading } from "../labels";

export interface DayBandProps {
  readonly day: Day;
  /** Every notice the DAY carries: that it is unconfirmed, a refused confirmation, a backfill's result. */
  readonly notices: readonly Notice[];
  readonly onConfirm: () => void;
  readonly onBackfill: () => void;
}

export function DayBand({ day, notices, onConfirm, onBackfill }: DayBandProps) {
  return (
    <div className="flex flex-col gap-2.75">
      <Strip>
        <StatCell label="blocks" figure={day.blockCount} />
        <StatCell label="presumed complete" figure={day.presumedCount} />
        <StatCell
          label="unconfirmed days"
          figure={day.unconfirmedDays}
          sub="past days, over the last 28"
        />
        <StatCell label="confirmed" figure={confirmationReading(day)} />
        <span className="ml-auto flex items-center gap-2">
          {day.unconfirmedDays === 0 ? null : (
            <Button rank="secondary" onClick={onBackfill}>
              {backfillLabel(day.unconfirmedDays)}
            </Button>
          )}
          <Button isDisabled={day.blockCount === 0} onClick={onConfirm}>
            Confirm the day
          </Button>
          {/* The hint sits BESIDE the primary button rather than inside it. The kit's key hint is drawn in
              --ink-deep with no inverse form, and the primary rank's fill is ink: inside, the brackets are
              ink on ink and a reader cannot see the keystroke the screen is advertising. */}
          <KeyHint keys="c" />
        </span>
      </Strip>
      {notices.map((notice) => (
        <NoticeCard key={notice.id} notice={notice} />
      ))}
    </div>
  );
}
