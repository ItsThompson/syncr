/* The three statements this screen makes in prose, and why they are the api's own words.
 *
 * SECTION 11 ASKS FOR ALL THREE EXPLICITLY, on the screen, in prose: that collecting is normal, that unlocks
 * depend on confirmed volume rather than on adherence, and that the thresholds are estimates. They are the
 * difference between a table of numbers and a surface a reader can check syncr against.
 *
 * THEY ARRIVE FROM THE API RATHER THAN LIVING HERE. A caveat that lives only in a template is one a client can
 * render without, and the CLI would then state the rule differently or not at all. The api serves them beside
 * the figures they are about.
 *
 * NO SIGNAL PIGMENT, AND NO NOTICE SURFACE. These are statements about how the product works, not conditions a
 * reader has to attend to. An amber panel saying "collecting is normal" would contradict itself. */

import { Panel } from "../../../ui/layout";
import type { Learned } from "../../../api/hooks/useLearned";

export interface GateStatementsProps {
  readonly learned: Learned;
}

export function GateStatements({ learned }: GateStatementsProps) {
  return (
    <Panel title="What these figures are">
      <div className="flex flex-col gap-2.75">
        <p className="text-base text-ink">{learned.collectingIsNormal}</p>
        <p className="text-base text-ink">{learned.unlocksCountConfirmedVolume}</p>
        <p className="text-base text-ink">{learned.thresholdsAreEstimates}</p>
      </div>
    </Panel>
  );
}
