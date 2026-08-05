/* The four steps of first run, and where each one stands.
 *
 * PURE, AND IT IS THE WHOLE OF THE SCREEN'S LOGIC. The route reads four resources and hands them here; everything
 * about which step is current, which is blocked and what each row counts is decided in one function that takes
 * values and returns values.
 *
 * TWO STEPS ARE THE MINIMUM AND THE OTHER TWO ARE NOT. Areas and a day shape are what a week needs before a plan
 * can exist for it, which is `syncr_api.plans.readiness`'s own reading, and this module agrees with it BY
 * CONSTRUCTION rather than by coincidence: a day shape counts as declared when the WEEK PATTERN is declared, which
 * is exactly what the api checks. Counting templates instead would let this screen call setup complete while
 * `POST /solve` refused it naming the day shape, which is the disagreement this agreement exists to prevent.
 *
 * BLOCKED AND WAITING ARE TWO STATUSES because the dependency between steps is the thing a first-run reader has to
 * see. A day shape charges its slots to Areas, so declaring one before an Area exists is not something to attempt:
 * that step is blocked, and it says what blocks it in words rather than only in a dashed rule.
 *
 * THE CURRENT STEP IS DERIVED, NEVER CHOSEN. It is the first step that is neither done nor blocked, so a step is
 * reached by finishing the one before it. That is also why the rows are not links: setup renders the current step's
 * panel beneath the list.
 *
 * PROGRESS IS SERVER STATE, WHICH IS WHY LEAVING AND COMING BACK PRESERVES IT. There is no draft here and no
 * wizard cursor to lose: each step is done when the thing it asks for exists, so the ledger reads the same on the
 * second sitting as it did at the end of the first. */

import type { WizardStep, WizardStepStatus } from "../../ui/domain";

/**
 * What each step asks for, in the order the ledger lists them.
 *
 * These are this screen's own keys, so they are spelled for a reader of this module. The api's `MissingInput`
 * spells the second one `day_shape`: the two agree on which inputs the minimum is and on the order they are
 * reported in, which is what a reader needs, and nothing maps one spelling onto the other because nothing yet
 * consumes the api's list. A consumer that does should map rather than assume.
 */
export type SetupStepId = "source" | "areas" | "day-shape" | "bounds";

/** What the four steps are decided from: one count or one presence per step. */
export interface SetupReads {
  readonly sourceCount: number;
  readonly areaCount: number;
  readonly dayShapeCount: number;
  /** Whether the week pattern is declared, which is what the api reads as a day shape existing. */
  readonly isPatternDeclared: boolean;
  /** The calendar holding the write-target role, or null when none does. */
  readonly writeTargetName: string | null;
}

/** Where a step points a reader who has to do something about it. */
export interface SetupStep extends WizardStep {
  readonly id: SetupStepId;
  /** The screen that authors this step's subject. */
  readonly href: string;
  /** What the step asks for and what depends on it, in the reader's words. */
  readonly statement: string;
  /** The control's own words on that screen, so the link says where to go rather than `continue`. */
  readonly actionLabel: string;
}

/**
 * The step whose panel is drawn, which is the only step a panel is ever drawn for.
 *
 * A separate type because a blocked step is never current: `withCaret` promotes a WAITING step, and a blocked one
 * is neither. Narrowing the panel's own prop is what makes that the compiler's business instead of a dead branch a
 * reader has to reason about.
 */
export type CurrentSetupStep = SetupStep & { readonly status: "current" };

/** Narrows a step to the current one, so `find` answers with the type the panel takes. */
export function isCurrent(step: SetupStep): step is CurrentSetupStep {
  return step.status === "current";
}

const REQUIRED_TO_SOLVE = "required to solve";
const OPTIONAL = "optional";

/** Which inputs the api reports missing, in setup order, so the two agree on WHICH inputs and on their order. */
export function missingMinimum(reads: SetupReads): readonly SetupStepId[] {
  const missing: SetupStepId[] = [];
  if (reads.areaCount === 0) missing.push("areas");
  if (!reads.isPatternDeclared) missing.push("day-shape");
  return missing;
}

/** True when a plan can be produced, which is the condition the root redirect turns on. */
export function isMinimumDeclared(reads: SetupReads): boolean {
  return missingMinimum(reads).length === 0;
}

/**
 * The four steps, each with its status, its note and its summary count.
 *
 * A completed step's note is its count, which is what a reader checks the claim against: `2 sources` says both
 * that the step is done and how much of it there is. An outstanding step's note is what it costs to skip.
 */
export function setupSteps(reads: SetupReads): readonly SetupStep[] {
  const areasDone = reads.areaCount > 0;
  const shapeDone = reads.isPatternDeclared;

  const statuses: Record<SetupStepId, WizardStepStatus> = {
    source: reads.sourceCount > 0 ? "done" : "waiting",
    areas: areasDone ? "done" : "waiting",
    "day-shape": dayShapeStatus({ shapeDone, areasDone }),
    bounds: reads.writeTargetName === null ? "waiting" : "done",
  };

  const current = (["source", "areas", "day-shape", "bounds"] as const).find(
    (id) => statuses[id] === "waiting",
  );

  const withCaret = (id: SetupStepId): WizardStepStatus =>
    id === current ? "current" : statuses[id];

  return [
    {
      id: "source",
      label: "Connect an anchor source",
      status: withCaret("source"),
      note: statuses.source === "done" ? plural(reads.sourceCount, "source") : OPTIONAL,
      href: "/settings",
      actionLabel: "Add a source on Settings",
      statement:
        "A feed becomes commitments syncr plans around. Nothing here is required to solve: without a " +
        "source the week is planned around an empty calendar, which is correct rather than broken.",
    },
    {
      id: "areas",
      label: "Declare Areas and budgets",
      status: withCaret("areas"),
      note: areasDone ? plural(reads.areaCount, "Area") : REQUIRED_TO_SOLVE,
      href: "/areas",
      actionLabel: "Declare Areas",
      statement:
        "Every discretionary block is charged to an Area, so a plan with nothing to charge to would " +
        "allocate the week to no category at all. This is the first of the two inputs a solve needs.",
    },
    {
      id: "day-shape",
      label: "Build one day shape",
      status: withCaret("day-shape"),
      note: shapeDone
        ? plural(reads.dayShapeCount, "day shape")
        : areasDone
          ? REQUIRED_TO_SOLVE
          : "blocked until an Area exists",
      href: "/templates",
      actionLabel: "Build a day shape",
      statement:
        "A day shape says what a kind of day holds, and the week pattern maps each weekday to one. With " +
        "no pattern nothing materializes and the circadian frame would be the entire plan. This is the " +
        "second input a solve needs, and it is counted as declared once every weekday is mapped.",
    },
    {
      id: "bounds",
      label: "Set the day bounds and the write target",
      status: withCaret("bounds"),
      /* The calendar's name rather than a count, which is where this note differs from the other three. One
         calendar may hold the role, so `1 write target` would be a count that can only ever read one way, and
         the name is what a reader checks the claim against. */
      note: reads.writeTargetName ?? OPTIONAL,
      href: "/settings",
      actionLabel: "Open Settings",
      statement:
        "The day bounds open the Week grid's axis and the write target is the one calendar syncr writes " +
        "the plan to, reconciled destructively. Both have defaults, so a week solves without either: " +
        "until a write target exists the plan simply stays inside syncr.",
    },
  ];
}

/** A day shape cannot be built before an Area exists to charge its slots to, which is a third state. */
function dayShapeStatus({
  shapeDone,
  areasDone,
}: {
  shapeDone: boolean;
  areasDone: boolean;
}): WizardStepStatus {
  if (shapeDone) return "done";
  if (!areasDone) return "blocked";
  return "waiting";
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}
