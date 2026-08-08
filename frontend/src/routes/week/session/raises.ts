/* THE SESSION'S RAISED ITEMS, NARROWED FROM THE WIRE TO WHAT THE KIT RENDERS.
 *
 * THE SENTENCE IS THE API'S AND THE HEADING IS THIS SCREEN'S. Each item arrives with the words to say about it, composed
 * server-side so the CLI and the screen cannot describe one week two ways, and every figure the item states is inside
 * that sentence: the payload carries no count field, because a number on the wire as well as in the words is a number a
 * surface could render twice. What the api does not carry is the eyebrow a group of them sits under: that is a label on
 * this surface, and the CLI's own listing has no groups at all.
 *
 * THE ORDER IS THE PAYLOAD'S. The api hands the categories in the order section 16's `raised` list gives them, and the
 * panel groups by first appearance, so which category a reader meets first is decided once, on the server, rather than
 * by a sort on each client.
 *
 * A KIND THIS BUILD DOES NOT KNOW STILL RENDERS. The heading falls back to the api's own word for the kind, so a
 * category added by a later api keeps its sentence and its title and loses only a nicety. A client that dropped the row
 * would hide something the product decided to raise, which is the opposite of what a raise is for. */

import type { RaisedItem, RaisedKind } from "../../../api/hooks/useWeeklySession";
import type { SessionRaise } from "../../../ui/domain";

/* The eyebrow each category's group sits under. A record over the generated union, so a kind the api adds is a
 * typecheck failure here rather than an unlabelled group on the screen. */
const HEADINGS: Record<RaisedKind, string> = {
  chronic_skip: "Chronically skipped",
  habit_at_debt_cap: "Habit at its debt cap",
  repeated_collision: "Repeated collision",
  overdue_task: "Overdue",
  at_risk_task: "At risk",
  floor_at_risk: "Floor at risk",
  new_anchor: "New commitment",
  cadence_due: "Cadence due",
};

/** The raises the panel draws, in the order the payload gave them. */
export function raisesOf(items: readonly RaisedItem[]): readonly SessionRaise[] {
  return items.map((item) => ({
    key: item.key,
    kind: item.kind,
    heading: HEADINGS[item.kind] ?? item.kind,
    title: item.title,
    statement: item.statement,
  }));
}
