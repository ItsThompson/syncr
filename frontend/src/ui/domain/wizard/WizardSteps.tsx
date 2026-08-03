/* The first-run wizard's steps: numbered ledger rows with a caret on the current one.
 *
 * NO PROGRESS BAR, and that is a decision rather than an omission: motion is zero, and progress that must be
 * shown is a count that changes. An ordered list also says what a bar cannot, which is WHICH step you are on and
 * which ones are blocked.
 *
 * THE NUMBER COMES FROM THE POSITION, so a caller cannot number two steps `02`. The row is static rather than a
 * link: setup renders the current step's own panel beneath this list, so a step is reached by finishing the one
 * before it, not by navigating to it.
 *
 * `aria-current="step"` AND `data-current` ARE BOTH DERIVED FROM ONE STATUS. The first is what a screen reader
 * announces and the second is the kit's row-state hook, which is where the fill and the 3px left rule come from:
 * `ui/primitives/states.css` assigns those two channels once for every row-shaped surface in the product.
 *
 * BLOCKED IS A CLASS AND NOT AN ATTRIBUTE, WHICH IS THE ONE PLACE THIS DEPARTS FROM THE KIT'S USUAL RULE. A row
 * here is not a control: it is a line in a list, and `aria-disabled` on a `li` is refused by the accessibility
 * lint because the listitem role does not support it. Nor is `blocked` an interaction state that could diverge from
 * an announced one, which is what the attribute rule protects against: it is DATA about the step, like its label.
 * What a reader hears instead is the note, which says what blocks it in words.
 *
 * The caret and the tick are markup rather than a state selector, because the closed state vocabulary has no
 * attribute for "done" and neither does ARIA. Both are chosen from the same status in the same place, and the
 * test asserts the caret lands on the row that carries `aria-current`.
 *
 * THE BORDERED BOX AROUND THE STEPS IS THE CALLER'S `Panel`. The list draws its rows and their hairlines and
 * nothing else, so the block's border and raised fill keep the one definition the layout layer gives them. */

import { cva } from "class-variance-authority";

import "../../primitives/glyphs.css";
import "../../primitives/states.css";
import "./wizard.css";

/* Blocked and waiting draw no mark, and the reserved column is what keeps the row's width from moving when one
 * of them becomes current. */
const mark = cva("glyph wizard__mark", {
  variants: {
    status: {
      done: "glyph--check wizard__mark--done",
      current: "glyph--caret",
      blocked: "",
      waiting: "",
    },
  },
});

const row = cva("state-row wizard__step", {
  variants: {
    status: {
      done: "",
      current: "",
      blocked: "wizard__step--blocked",
      waiting: "",
    },
  },
});

/**
 * Where a step stands.
 *
 * `blocked` is "you cannot start this yet" and `waiting` is "you have not started this yet". They are two
 * statuses rather than one because the dependency between steps is the thing a first-run reader has to see.
 */
export type WizardStepStatus = "done" | "current" | "blocked" | "waiting";

export interface WizardStep {
  readonly id: string;
  /** What the step asks the reader to do, in a sentence. */
  readonly label: string;
  readonly status: WizardStepStatus;
  /**
   * The right-hand word: `required`, `required to solve`, `optional`, or what blocks it.
   *
   * A blocked step states its blocker here, because a dashed rule says a step cannot be started and only words
   * say why.
   */
  readonly note?: string | undefined;
}

export interface WizardStepsProps {
  readonly steps: readonly WizardStep[];
  /** Names the list, which is what a screen reader announces before the first step. */
  readonly label: string;
}

export function WizardSteps({ steps, label }: WizardStepsProps) {
  return (
    <ol aria-label={label}>
      {steps.map((step, index) => (
        <li
          key={step.id}
          className={row({ status: step.status })}
          data-current={step.status === "current" ? "" : undefined}
          aria-current={step.status === "current" ? "step" : undefined}
        >
          <span className="wizard__number">{String(index + 1).padStart(2, "0")}</span>
          <span className={mark({ status: step.status })} aria-hidden="true" />
          <span className="wizard__label">{step.label}</span>
          {step.note === undefined ? null : <span className="wizard__note">{step.note}</span>}
        </li>
      ))}
    </ol>
  );
}
