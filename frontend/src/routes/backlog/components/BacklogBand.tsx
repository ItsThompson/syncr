/* THE BACKLOG'S BAND: the two figures the server states, and the control that captures.
 *
 * THE COUNTS ARE THE SERVER'S AND THIS BAND COUNTS NOTHING. `openCount` and `atRiskCount` are computed over the
 * Area's open tasks whatever the filters select, so the band states the backlog while the table's footer states
 * the rows on screen. A band that counted its own rows would disagree with itself the moment a filter moved,
 * and the at-risk figure is not one a client could make at all: it is the week verdict's determination, so the
 * same shortfall the verdict panel renders is what this figure counts.
 *
 * THE KEYSTROKE IS ADVERTISED BESIDE THE CONTROL rather than inside it, which is the pattern the day band
 * already sets: the key hint is drawn in ink and the primary rank's own fill is ink, so inside it a reader
 * cannot see the keystroke the screen is advertising. */

import { CAPTURE_KEY, KeyHint, NoticeCard, type Notice } from "../../../ui/domain";
import { StatCell, Strip } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import type { BacklogHeader } from "../../../api/hooks/useBacklog";

export interface BacklogBandProps {
  readonly header: BacklogHeader;
  /** Every notice the SCREEN carries: a completion that landed, or a write the api refused. */
  readonly notices: readonly Notice[];
  readonly onCapture: () => void;
}

export function BacklogBand({ header, notices, onCapture }: BacklogBandProps) {
  return (
    <div className="flex flex-col gap-2.75">
      <Strip>
        <StatCell label="open tasks" figure={header.openCount} />
        <StatCell label="at risk" figure={header.atRiskCount} sub="named by this week's verdict" />
        <span className="ml-auto flex items-center gap-2">
          <Button onClick={onCapture}>Capture a task</Button>
          <KeyHint keys={CAPTURE_KEY} />
        </span>
      </Strip>
      {notices.map((notice) => (
        <NoticeCard key={notice.id} notice={notice} />
      ))}
    </div>
  );
}
