/* THE HEAD OF THE WEEK SCREEN: what is broken, what is impossible, and what this week has already conceded.
 *
 * THE ORDER IS THE ORDER A READER SHOULD MEET THEM IN. A refusal is about the gesture they just made, so it comes
 * first; an unanswered conflict is the one condition that pushes, so it comes next; the verdict is the standing state
 * of the week, so it comes last and stays.
 *
 * THE VERDICT PANEL IS ALWAYS DRAWN WHERE THERE IS A VERDICT, feasible or not. A panel that appeared only on a
 * shortfall would change the height of this region as pins land, which is the shift the fixed height exists to
 * prevent, and it would leave a reader unable to tell "no gap" from "not computed".
 *
 * NOTHING HERE BLOCKS ANYTHING. Every notice is inline, panel or banner: level 4 does not exist, and `Approve` sits in
 * the band above whatever this region says. */

import { NoticePanel, VerdictPanel } from "../../../ui/domain";
import type { Notice, PanelVerdict, VerdictConcession, VerdictTradeoff } from "../../../ui/domain";
import { ConflictBanner, type ConflictAnswer } from "./ConflictBanner";

/** One unanswered overlap, with the three answers it offers and nothing chosen. */
export interface BannerConflict {
  readonly id: string;
  readonly notice: Notice;
  readonly answers: readonly ConflictAnswer[];
  readonly templateHref?: string | undefined;
}

export interface WeekHeadProps {
  /** Panel-volume notices: a refused write, a failed solve. */
  readonly notices: readonly Notice[];
  readonly conflicts: readonly BannerConflict[];
  /** The week's verdict, or null when the week holds no plan and nothing has computed one. */
  readonly verdict: PanelVerdict | null;
  readonly concessions: readonly VerdictConcession[];
  readonly onPropose: (tradeoff: VerdictTradeoff) => void;
}

export function WeekHead({ notices, conflicts, verdict, concessions, onPropose }: WeekHeadProps) {
  if (notices.length === 0 && conflicts.length === 0 && verdict === null) return null;

  return (
    <div className="flex flex-col gap-3">
      {notices.map((notice) => (
        <NoticePanel key={notice.id} notice={notice} />
      ))}
      {conflicts.map((conflict) => (
        <ConflictBanner
          answers={conflict.answers}
          key={conflict.id}
          notice={conflict.notice}
          templateHref={conflict.templateHref}
        />
      ))}
      {verdict === null ? null : (
        <VerdictPanel concessions={concessions} onPropose={onPropose} verdict={verdict} />
      )}
    </div>
  );
}
