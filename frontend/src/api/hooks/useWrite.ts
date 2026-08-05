/* The write half of a hook: one function to call, and the last refusal to render.
 *
 * A read hook returns a `Resource<T>`, which is the whole state of a read. A write has a different
 * shape and pretending otherwise would be worse: there is no `data`, the interesting state is the
 * refusal, and a form has to keep rendering the values the reader typed while the refusal is on
 * screen. So a write hook returns the call and the problem, and nothing else.
 *
 * THERE IS NO `isSubmitting` FLAG, and that is not an omission. Nothing in this product may spin, so a
 * flag whose only use is drawing a spinner would have no reader. A count that changes is how progress
 * is reported here, and a write that changes one row has no count to change.
 *
 * The problem is replaced on every attempt: a submit that lands clears it, and a submit that is
 * refused replaces it. A reader who fixes the named member sees the notice go when the next attempt
 * succeeds, which is the moment the statement stops being true. */

import { useState } from "react";

import type { Problem } from "../../contract";
export interface Write<Body> {
  /** True when the change was applied. False leaves `problem` naming what refused it. */
  readonly submit: (body: Body) => Promise<boolean>;
  /** The last refusal, or null when nothing has been refused since the last successful write. */
  readonly problem: Problem | null;
  /**
   * Forget the last refusal, for a caller whose ONE write serves several rows.
   *
   * A refusal is the last one whatever produced it, which is right for a form: it stands until the reader fixes
   * the member it names. It is wrong for a table where one write serves every row, because the refusal outlives
   * the row that caused it and then appears inside another row's editor, naming an Area the reader never
   * touched. The caller that knows which row is open is the one that can say when the refusal stopped being
   * true, so this is a control the caller reaches for rather than a rule the hook invents.
   */
  readonly clear: () => void;
}

/**
 * A write, given the request AND its invalidation.
 *
 * `perform` owns both halves deliberately: the key a change invalidates is a fact about that change,
 * and a hook that invalidated on its caller's behalf would have to be told the key anyway. Returning
 * the problem rather than throwing keeps every refusal on the one path a form renders from.
 */
export function useWrite<Body>(perform: (body: Body) => Promise<Problem | null>): Write<Body> {
  const [problem, setProblem] = useState<Problem | null>(null);

  const submit = async (body: Body): Promise<boolean> => {
    const refusal = await perform(body);
    setProblem(refusal);
    return refusal === null;
  };

  return { submit, problem, clear: () => setProblem(null) };
}

/**
 * The refusal a write with nothing selected answers with.
 *
 * Three writes on this screen belong to one row, and a caller that renders their form with no row selected is
 * reachable in principle: the screens do not do it, and a silent no-op would leave anyone who managed it with a
 * control that did nothing and said nothing. One factory rather than three literals, because the sentence is the
 * same one three times and the only difference is the noun.
 *
 * `status` is 0, which no HTTP response can carry: nothing was sent, so there is no status to report.
 */
export function nothingSelectedProblem(subject: string, chooseFrom: string): Problem {
  return {
    type: "syncr:nothing-selected",
    title: `No ${subject} is selected`,
    status: 0,
    detail:
      `A change belongs to one ${subject}, and none is selected, so nothing was sent. ` +
      `Choose a ${subject} from the ${chooseFrom} and make the change again.`,
  };
}
