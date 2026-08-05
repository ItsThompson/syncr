/* Where `/` goes: the week, or setup when the minimum does not exist.
 *
 * THE DECISION NEEDS A READ, WHICH IS WHY THIS IS A COMPONENT RATHER THAN A `Navigate`. The route table declared
 * `/` as a redirect to the week and said so in a comment: sending a reader with no plan to setup instead needs the
 * setup-completeness reading, and this is where it arrives.
 *
 * A REFUSED READ GOES TO THE WEEK. A reader whose Areas could not be fetched has not lost their Areas, and sending
 * them to setup on a 503 would be the product telling them to declare what they already have. The Week screen's own
 * empty state renders whatever reason the api gives for a week with no plan, so the honest failure mode is to carry
 * on and let the screen that knows say it.
 *
 * IT REPLACES RATHER THAN PUSHES, in both directions. `/` is not a destination a reader should be able to go back
 * to: back from the week belongs to whatever they were doing before syncr, not to a redirect that would bounce them
 * forward again.
 *
 * THE WAIT IS A SENTENCE, NOT A SPINNER, and it is the shortest-lived surface in the product: two list reads and
 * two small ones. Rendering nothing at all would be a blank screen with no explanation, which is the one thing the
 * status family exists to replace. */

import { Navigate } from "react-router";

import { PendingState } from "../ui/domain";
import { DEFAULT_RETURN_PATH } from "../app/signIn";
import { SETUP_PATH } from "../ui/domain/shell/navigation";
import { isSetupRequired, useSetupReads } from "./setup";

export function RootRedirect() {
  const reads = useSetupReads();

  if (reads.status === "loading") {
    return (
      <PendingState
        title="Reading your setup"
        detail="Whether your Areas and a day shape exist, which is what a plan needs before one can be produced."
      />
    );
  }

  return <Navigate to={isSetupRequired(reads) ? SETUP_PATH : DEFAULT_RETURN_PATH} replace />;
}
