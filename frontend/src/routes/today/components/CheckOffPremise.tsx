/* What the ledger is for, stated once on the screen it governs.
 *
 * It is here because the screen's whole shape follows from it: blocks are presumed complete, so per-block
 * check-off is optional, so the evening pass is what records the day. A reader who does not know that reads
 * an empty outcome column as work they have not done.
 *
 * THE KEYS LIVE HERE TOO, because a bare keystroke acts on the row holding focus and nothing on a row says
 * so. The shell's help overlay lists the same bindings; what this adds is which row they land on. */

import { Panel } from "../../../ui/layout";
import { KeyHint } from "../../../ui/domain";

export function CheckOffPremise() {
  return (
    <Panel
      title="Per-block check-off is optional"
      headerEnd={<span className="text-eyebrow">the evening pass is what records the day</span>}
    >
      <div className="flex flex-col gap-2 p-2.75 text-sm text-ink-soft">
        <p>
          Blocks are presumed complete unless you say otherwise, which keeps the daily cost of using
          syncr near zero. Confirming converts presumed to recorded, for every block of the day
          including the ones still ahead in it. A day you never confirm is excluded from both
          reviews and learning, which is what stops a week you disengaged from being recorded as
          perfect.
        </p>
        <p>
          Mark only the exceptions. Focus a row, then <KeyHint keys="x" /> skips it,{" "}
          <KeyHint keys="Shift+X" /> opens the minutes it really took, and <KeyHint keys="m" />{" "}
          opens the interval it really ran in. <KeyHint keys="c" /> confirms the day.
        </p>
      </div>
    </Panel>
  );
}
