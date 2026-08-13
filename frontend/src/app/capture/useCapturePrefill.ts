/* LANDING A READER THE URL INVITED, AND TAKING THE INVITATION BACK OUT OF THE ADDRESS BAR.
 *
 * MOUNTED BY THE SCREEN THE URL NAMES, which is the Backlog: a task is authored there, so that is where a capture
 * invited from another screen arrives. The host above the route owns the dialog; what this owns is reading the
 * question and answering it once.
 *
 * IT DOES NOT WAIT FOR THE SCREEN'S OWN READS. Capture is the shell's, not the Backlog's, and a reader whose
 * backlog read failed must still be able to capture: that is the whole reason `n` is global. So this runs on every
 * state of the screen, including the failed one.
 *
 * THE PARAMETERS ARE REPLACED RATHER THAN PUSHED, so the entry the reader would go BACK to is the screen they came
 * from rather than the invitation they have already accepted. Pushing would also make the browser's back button
 * reopen the dialog, which is the same defect a reload would be. */

import { useEffect } from "react";
import { useSearchParams } from "react-router";

import { useCapture } from "./captureContext";
import { capturePrefillIn, withoutCapturePrefill } from "./prefill";

/** Opens capture from the URL that asked for it, once, and clears what asked. */
export function useCapturePrefill(): void {
  const [search, setSearch] = useSearchParams();
  const capture = useCapture();

  useEffect(() => {
    const prefill = capturePrefillIn(search);
    if (prefill === null) return;
    /* RETURN TO NOTHING, NAMED AS NULL. The control that asked for this opening is on a screen the reader has left,
     * so there is nothing to go back to, and the host's fallback of reading `document.activeElement` would name the
     * document body: focusing that on close is a claim rather than an answer, where naming null leaves the return
     * to the dialog family's own policy. */
    capture.open({ ...prefill, returnFocusTo: null });
    setSearch(withoutCapturePrefill(search), { replace: true });
  }, [search, setSearch, capture]);
}
