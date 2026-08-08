/* `/learned`: THE TRUST SURFACE. Not a diagnostic panel.
 *
 * WHAT THE SCREEN IS FOR decides what is on it. A reader opens this to check syncr against their own experience,
 * so every element answers a question they actually have: is anything wrong (no), what has it worked out about
 * me (the value and its sentence), how far off is the rest (the meter and the two counts), what do my own actions
 * teach it (the sources), and can I undo a bad fit (the versions). A diagnostic panel would carry the fitted
 * floats and stop there.
 *
 * NOTHING HERE IS A WARNING. Collecting is the normal state of a working system in its first weeks, and section
 * 11 is explicit that marking it in oxide would teach the reader to distrust it. So no signal pigment appears on
 * this screen at all, and the three statements say in prose what a badge cannot.
 *
 * THE EMPTY STATE IS THE FIRST TWO WEEKS, AND IT IS PART OF THE PRODUCT. The learning layer produces nothing
 * until the nightly run has a corpus, so a fresh account's active weight set carries no maturity rows at all and
 * the read answers with none. That is `Collecting baseline`, stated at informational volume and static. The
 * statements and the sources still render under it, because a screen that showed only two words would teach a
 * reader nothing about what to do next, and what to do next is exactly nothing.
 *
 * TWO READS, ONE READING. The parameters and the versions are two resources answering two questions, and the
 * screen cannot draw two thirds of itself: `readingOf` narrows both to one state and names the read that failed.
 *
 * THE BAND RENDERS BEFORE EITHER READ DOES, and every state under it is static. A pending read says what it is
 * waiting for in words; there is no spinner in this kit to reach for. */

import { EmptyState, PendingState } from "../../ui/domain";
import { useLearned, useWeightSetActivation, useWeightSets } from "../../api/hooks/useLearned";
import { readingOf } from "../reading";
import { ReadFailure } from "../templates/components/ReadFailure";
import { GateStatements } from "./components/GateStatements";
import { LearnedBand } from "./components/LearnedBand";
import { ParameterTable } from "./components/ParameterTable";
import { SignalSourceTable } from "./components/SignalSourceTable";
import { WeightSetPanel } from "./components/WeightSetPanel";
import type { ReactElement } from "react";
import type { Learned } from "../../api/hooks/useLearned";

/** What a fresh account reads, and what it means. Static, informational, and never a warning. */
const BASELINE_DETAIL =
  "Nothing has been fitted yet, and nothing is wrong. syncr fits a parameter only once it has enough " +
  "confirmed evidence to be worth trusting, which takes a fortnight for the fastest of them. Until then the " +
  "plan is solved with the hand-tuned weights below, and every day you confirm counts towards the first fit.";

/* The band is drawn above whatever the state is, so the destination names itself while the figures are still
 * coming. Its counts are absent until they are known rather than zero, which is a reading of its own.
 *
 * At module scope because it captures nothing: it takes the surface and the reading it draws from. */
function under(surface: ReactElement, learning?: Learned) {
  return (
    <>
      <LearnedBand
        collecting={learning?.collecting}
        ready={learning?.ready}
        version={learning?.version}
        origin={learning?.origin}
      />
      <div className="flex flex-col gap-3.25 px-3.75 py-3.25">{surface}</div>
    </>
  );
}

export function LearnedRoute() {
  const learned = useLearned();
  const versions = useWeightSets();
  const activate = useWeightSetActivation();

  const answered = readingOf({ learning: learned, versions });

  if (answered.status === "loading") {
    return under(
      <PendingState
        title="Reading what has been learned"
        detail="Every parameter, the evidence behind it, and which weight set is in force."
      />,
    );
  }
  if (answered.status === "error") {
    return under(
      <ReadFailure title={`The ${answered.name} could not be read`} problem={answered.problem} />,
    );
  }

  const { learning, versions: held } = answered.data;

  return under(
    <>
      {learning.parameters.length === 0 ? (
        <EmptyState title="Collecting baseline" detail={BASELINE_DETAIL} />
      ) : (
        <ParameterTable parameters={learning.parameters} />
      )}
      <GateStatements learned={learning} />
      <SignalSourceTable />
      <WeightSetPanel versions={held} activate={activate} />
    </>,
    learning,
  );
}
