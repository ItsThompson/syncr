/* THE RAISED-ITEMS PANEL: everything the weekly session opens with, at panel volume in amber.
 *
 * PANEL VOLUME, IN AMBER, AND IN SESSION MODE ONLY. Section 16's notice-volume table gives every session raise one
 * volume and one pigment: a chronic skip reads "needs attention, nothing is broken". The surface is `noticeSurface`'s
 * own amber panel rather than a second declaration of it, so this panel and every other volume-2 amber notice in the
 * product cannot come to look different. The table's OTHER session row, an available promotion, takes the same surface
 * in its own panel rather than a row here, because the reader needs the binding, the time and the count per candidate
 * and those are a table rather than a sentence.
 *
 * NOTHING HERE IS AN ACTION, and the absence is the design. There is deliberately no "carry forward": an overdue task
 * is already in the backlog, so the affordance would be a control that changes nothing. A chronic skip offers nothing
 * because `US-REV-02` leaves reschedule, cut scope, or drop to the reader. A repeated collision offers nothing because
 * the fix could be a template change, an anchor type, or nothing at all.
 *
 * A SESSION WITH NOTHING RAISED SAYS SO. An empty panel would read as a panel that failed to load, and "nothing is
 * outstanding" is the most useful thing the session can tell a reader who has been keeping up. */

import { noticeRole, noticeSurface } from "../notices/surface";
import { groupRaises, type SessionRaise } from "./raises";
import "../notices/notices.css";

const NOTHING_RAISED =
  "Nothing is outstanding: no chronic skip, no floor at risk, no overdue task, and no repeated collision.";

export interface RaisedPanelProps {
  readonly raises: readonly SessionRaise[];
}

export function RaisedPanel({ raises }: RaisedPanelProps) {
  const groups = groupRaises(raises);

  return (
    <section
      aria-label="Raised in this session"
      className={noticeSurface({ volume: "panel", pigment: "amber" })}
      role={noticeRole("amber")}
    >
      <div className="notice__content">
        {groups.length === 0 ? <p className="notice__detail">{NOTHING_RAISED}</p> : null}
        {groups.map((group) => (
          <div key={group.kind}>
            <b className="notice__title">{group.heading}</b>
            {group.raises.map((raise) => (
              <p key={raise.key} className="notice__detail">
                <b>{raise.title}</b>
                <span className="notice__capability">{raise.statement}</span>
              </p>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
