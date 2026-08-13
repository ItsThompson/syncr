/* THE ONE CAPTURE THE WHOLE APPLICATION SHARES: the `n` binding, the reads the form needs, and the two writes.
 *
 * MOUNTED ABOVE THE ROUTE, so `n` opens capture from any screen and a screen that wants a control for it asks
 * this host through `useCapture` rather than mounting a second dialog. One instance is what keeps two forms
 * from holding two drafts of the same task.
 *
 * TWO LIFETIMES, AND EVERY DEFECT IN THIS FILE SO FAR CAME FROM CONFLATING THEM.
 *
 *   the DIALOG   one opening: its draft, where focus returns, and which refusal belongs to it. Ends when the
 *                reader dismisses or when a send it owns lands
 *   the REQUEST  one confirm's writes: begins when the lock is taken and ends when the api has answered them,
 *                whatever the reader does to the dialog in between
 *
 * A dismiss ends the dialog and does NOT end the request, so nothing a dismiss does may touch the lock, and
 * nothing a resolved send does may touch a dialog it no longer owns. `generation` is what says which opening a
 * send belongs to: it is bumped on every open and every close, so a send that started under a previous number
 * applies nothing. Three defects lived in the gap between those two sentences: a dismiss released the lock while
 * the POST was still open and let a second identical task be captured; a resolved send tore down a dialog the
 * reader had reopened and typed into; and a refusal for a discarded draft would have rendered on the new one.
 *
 * THE MOVES THE OPENING MAKES ARE IN `captureState`, as pure functions of the state and the api's answer, so the
 * four outcomes of a send are readable and assertable without a rendered dialog. What is here is when they run.
 *
 * ONE SEND AT A TIME, because a capture WRITES. Two clicks of an ordinary double-tap, or a dismiss and a retype
 * while the first request is still open, would otherwise put two tasks in the backlog. The lock is a ref and the
 * disabled control is what tells the reader: `disabled` reaches the DOM on the next render, and nothing
 * guarantees a render commits between the two clicks of a double-tap. `Idempotency-Key` would make the api
 * answer a RETRY with the first request's task, which is the case no client-side lock can reach and which no
 * request on this path sends a key for.
 *
 * FOCUS RETURNS TO WHERE THE READER WAS, AND THE ELEMENT IS THE CALLER'S. Radix restores focus when it can see
 * the trigger that opened the dialog; a chord has no trigger, and measured in this environment the reader lands
 * on the document body. So `open` reads `document.activeElement` at the moment it is called, which is inside the
 * keystroke's own handler and the last instant the answer still exists. A caller whose own control will not
 * SURVIVE the write names a surviving one instead, which is what the empty backlog's prompt does: capturing the
 * first task replaces the prompt with a table, so returning to it would return to nothing.
 *
 * THE AREAS ARE READ HERE AND NOT IN THE DIALOG. A capture needs an Area and the Area list is where the names
 * are, so the read belongs to the host: the form takes the pairs as a prop and is testable without a fixture.
 * The list is read whether or not the dialog is open, because it is the shell's own read and a reader pressing
 * `n` must not wait for it.
 *
 * THE DRAFT IS DISCARDED WHEN THE DIALOG CLOSES AND KEPT WHILE IT IS REFUSED. A reader whose title was too long
 * has to be able to fix the title, and a reader who just captured a task wants an empty form the next time. */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useAreas } from "../../api/hooks/useAreas";
import { useSettings } from "../../api/hooks/useSettings";
import { useTaskCapture } from "../../api/hooks/useTaskCapture";
import { useKeyBinding } from "../../lib/keyboard";
import { todayIn } from "../../lib/zonedInstant";
import { CAPTURE_KEY } from "../../ui/domain";
import { notSavedNotice, useClientNotices } from "../notices";
import { CaptureContext, type Capture, type CaptureOpening } from "./captureContext";
import { CaptureDialog } from "./CaptureDialog";
import { closedAfter, noOpening, openedOn, stateAfter, type CaptureState } from "./captureState";
import { preferredWindowDeclaration, preferredWindowReading } from "./preferredWindow";
import { captureRefusedNotice, refusalsFrom, sendStillOpenNotice } from "./refusals";
import { bodyOf, deadlineInstantOf, isSubmittable, refusalsIn, type CaptureDraft } from "./draft";
import type { CaptureWindow } from "./preferredWindow";

/* The zone the date field and a deadline are read in before the settings read lands. A reader who presses `n` in
 * that window and fills in a deadline would resolve it in UTC rather than in their own zone; what makes that
 * narrow is that the read is the shell's and is already in flight when the screen draws. */
const ZONE_BEFORE_SETTINGS = "UTC";

export interface CaptureHostProps {
  readonly children: ReactNode;
}

export function CaptureHost({ children }: CaptureHostProps) {
  const areas = useAreas();
  const settings = useSettings();
  const write = useTaskCapture();
  const { report } = useClientNotices();
  const [state, setState] = useState<CaptureState>(noOpening);
  /* THE REQUEST, which outlives the dialog that started it. `isSending` is what disables the control and the ref
   * is the same fact answerable inside a click handler, where the state is one render too late. Both move in
   * `taken` and `released` and nowhere else, so they cannot drift apart. */
  const [isSending, setSending] = useState(false);
  const inFlight = useRef(false);

  const zone = settings.status === "ready" ? settings.data.homeZone : ZONE_BEFORE_SETTINGS;
  const listed = areas.status === "ready" ? areas.data.areas : [];

  /* HELD ACROSS RENDERS, and it can be: opening only sets state, and a state setter is stable. A value rebuilt
   * on every render would redraw every screen reading the context on every keystroke in the form. */
  const capture = useMemo<Capture>(
    () => ({
      open: (opening: CaptureOpening = {}) => {
        const wasOn = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        /* NAMED-AS-NULL IS NOT THE SAME AS NOT NAMED. A caller whose control will not survive its own write
         * names one that will, and if the ref it names is empty it means "return to nothing" rather than "fall
         * back to the control I already know is doomed": `??` would have re-admitted the defect that made this
         * explicit, on the empty backlog's prompt. Unreachable today, because the band renders before the prompt
         * can be pressed, which is why it is stated here rather than left to hold by accident. */
        const returnFocusTo = "returnFocusTo" in opening ? (opening.returnFocusTo ?? null) : wasOn;
        setState((held) => openedOn(held, opening, returnFocusTo));
      },
      isAvailable: true,
    }),
    [],
  );

  useKeyBinding({ key: CAPTURE_KEY }, capture.open);

  /**
   * The reader dismissed the form.
   *
   * It ends the OPENING and not the request: a POST already sent will be applied whatever this form does, so
   * releasing the lock here is what let a second identical task be captured. The generation moves so the send in
   * flight owns nothing, and a refusal it answers with is reported in the top bar instead of inside a form that
   * no longer exists.
   */
  const close = () => {
    setState(closedAfter);
  };

  /** Take the lock, or answer false because a request this host sent has not been answered yet. */
  const taken = (): boolean => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setSending(true);
    return true;
  };

  const released = () => {
    inFlight.current = false;
    setSending(false);
  };

  /**
   * Send the draft, once, on behalf of the opening that asked, and the preferred time it came from.
   *
   * THE WINDOW IS PASSED IN RATHER THAN READ HERE, with the draft and the generation, so all three are the
   * opening's own as it stood at the confirm rather than as it stands when the api answers.
   *
   * The generation is captured before the request and compared after it, so a send whose dialog the reader has
   * dismissed or replaced changes nothing: it neither closes a form the reader is typing into nor states a
   * refusal about a draft that no longer exists.
   *
   * THE LOCK IS RELEASED IN A `finally`, because a lock taken before an `await` and released after it is a lock
   * a rejection keeps for the rest of the session: the form would then refuse every later capture with no way
   * back.
   *
   * IT IS NOT DRIVEN, AND THAT IS NOT THE SAME AS UNTESTABLE. No production call site can make this reject:
   * `apply` and `answered` each answer a `Problem` rather than throwing, by construction, and the SWR
   * filter-mutate the write ends with resolves even when the re-read fails, measured at 500 and at transport
   * failure, with and without a subscriber. A test would have to force a shape the wiring cannot produce, which
   * is the one defect class this repository keeps finding. What the `finally` is for is the day SWR's behaviour
   * changes: if a rejection ever becomes reachable here, drive it by making `write.submit` reject and assert the
   * control is enabled again.
   */
  const submit = async (held: CaptureDraft, generation: number, window: CaptureWindow | null) => {
    if (!taken()) return;

    try {
      /* A WINDOW THE FORM COULD NOT STATE IS NOT SENT EITHER, which is one rule and not two: the reading and the
       * declaration are both null for an instant or a zone that cannot be read, so a reader never confirms a
       * preferred time they were not shown. */
      const outcome = await write.submit({
        task: bodyOf(held, deadlineInstantOf(held.deadline, zone)),
        preferredWindow: window === null ? null : preferredWindowDeclaration(window, zone),
      });

      setState((current) => stateAfter(current, generation, outcome));
    } finally {
      released();
    }
  };

  /* THE OTHER CHANNEL, FOR THE REFUSAL NO FORM IS LEFT TO STATE. It is raised after the commit rather than in the
   * send, because the api's own sentence arrives on the write hook's state: the send's continuation holds which
   * write was refused and not the words. One send at a time, so the problem standing when the write is named is
   * that send's. Clearing the name is this host's business and dismissing the banner is the reader's, which the
   * notice source owns: a notice raised twice replaces whatever stands under its id, so one refused capture is one
   * banner however many times it is reported. */
  useEffect(() => {
    const refused = state.refusalToReport;
    if (refused === null || write.problem === null) return;
    report(notSavedNotice(refused, write.problem));
    setState((current) => ({ ...current, refusalToReport: null }));
  }, [state.refusalToReport, write.problem, report]);

  /* The refusal is shown only to the opening it was refused for. A send the reader dismissed can still answer,
   * and its sentence names a draft that is gone. */
  const refusal = state.refusedAt === state.generation ? write.problem : null;
  const notice =
    refusal !== null
      ? captureRefusedNotice(refusal)
      : isSending && state.refusedAt === null
        ? sendStillOpenNotice()
        : undefined;
  /* THE WINDOW IN THE READER'S OWN ZONE, resolved here because the zone is this host's read: the form is handed
   * words for the same reason it is handed a date rather than a zone. */
  const windowStated =
    state.preferredWindow === null
      ? undefined
      : (preferredWindowReading(state.preferredWindow, zone) ?? undefined);

  return (
    <CaptureContext.Provider value={capture}>
      {children}
      <CaptureDialog
        areas={listed.map((area) => ({ id: area.id, name: area.name }))}
        canSubmit={isSubmittable(state.draft) && !isSending}
        draft={state.draft}
        isOpen={state.isOpen}
        notice={notice}
        onDraftChange={(draft) => setState((current) => ({ ...current, draft }))}
        onOpenChange={(next) => {
          if (!next) close();
        }}
        onSubmit={() => {
          void submit(state.draft, state.generation, state.preferredWindow);
        }}
        preferredWindowReading={windowStated}
        refusals={{ ...refusalsIn(state.draft), ...refusalsFrom(refusal) }}
        returnFocusTo={state.returnFocusTo}
        today={todayIn(zone, Date.now())}
      />
    </CaptureContext.Provider>
  );
}
