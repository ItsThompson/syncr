/* THE ONE CAPTURE THE WHOLE APPLICATION SHARES: the `n` binding, the reads the form needs, and the write.
 *
 * MOUNTED ABOVE THE ROUTE, so `n` opens capture from any screen and a screen that wants a control for it asks
 * this host through `useCapture` rather than mounting a second dialog. One instance is what keeps two forms
 * from holding two drafts of the same task.
 *
 * TWO LIFETIMES, AND EVERY DEFECT IN THIS FILE SO FAR CAME FROM CONFLATING THEM.
 *
 *   the DIALOG   one opening: its draft, where focus returns, and which refusal belongs to it. Ends when the
 *                reader dismisses or when a send it owns lands
 *   the REQUEST  one POST: begins when the lock is taken and ends when the api answers, whatever the reader
 *                does to the dialog in between
 *
 * A dismiss ends the dialog and does NOT end the request, so nothing a dismiss does may touch the lock, and
 * nothing a resolved send does may touch a dialog it no longer owns. `generation` is what says which opening a
 * send belongs to: it is bumped on every open and every close, so a send that started under a previous number
 * applies nothing. Three defects lived in the gap between those two sentences: a dismiss released the lock while
 * the POST was still open and let a second identical task be captured; a resolved send tore down a dialog the
 * reader had reopened and typed into; and a refusal for a discarded draft would have rendered on the new one.
 *
 * ONE SEND AT A TIME, because a capture WRITES. Two clicks of an ordinary double-tap, or a dismiss and a retype
 * while the first request is still open, would otherwise put two tasks in the backlog. The lock is a ref and the
 * disabled control is what tells the reader: `disabled` reaches the DOM on the next render, and nothing
 * guarantees a render commits between the two clicks of a double-tap. `Idempotency-Key` would make the api
 * answer a RETRY with the first request's task, which is the case no client-side lock can reach and which
 * ticket 1462 owns.
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
import { useTaskCapture } from "../../api/hooks/useBacklog";
import { useSettings } from "../../api/hooks/useSettings";
import { useKeyBinding } from "../../lib/keyboard";
import { todayIn } from "../../lib/zonedInstant";
import { CAPTURE_KEY } from "../../ui/domain";
import { captureNotSavedNotice, useClientNotices } from "../notices";
import { CaptureContext, type Capture, type CaptureOpening } from "./captureContext";
import { CaptureDialog } from "./CaptureDialog";
import { captureRefusedNotice, refusalsFrom, sendStillOpenNotice } from "./refusals";
import {
  bodyOf,
  deadlineInstantOf,
  emptyDraft,
  isSubmittable,
  refusalsIn,
  type CaptureDraft,
} from "./draft";

/* The zone the date field and a deadline are read in before the settings read lands. A reader who presses `n` in
 * that window and fills in a deadline would resolve it in UTC rather than in their own zone; what makes that
 * narrow is that the read is the shell's and is already in flight when the screen draws. */
const ZONE_BEFORE_SETTINGS = "UTC";

/** One opening of the dialog: what it holds, where it came from, and which refusal is its own. */
interface CaptureState {
  readonly isOpen: boolean;
  readonly draft: CaptureDraft;
  /**
   * The element focus returns to on close.
   *
   * READ AT THE MOMENT THE OPEN IS DECIDED, which is inside the keydown or the click that asked for it: that is
   * the last instant at which `document.activeElement` is still where the reader was. One render later the
   * dialog has the focus and the answer is gone.
   */
  readonly returnFocusTo: HTMLElement | null;
  /**
   * Which opening this is. Bumped on every open and every close.
   *
   * A send carries the number it started under and compares it before it changes anything, so a dismiss or a
   * reopen makes a resolved send inert rather than letting it act on a dialog that is no longer the one it
   * started with.
   */
  readonly generation: number;
  /** The opening the last refusal belongs to, so a refusal cannot land on a draft that replaced it. */
  readonly refusedAt: number | null;
  /**
   * A refusal answered for an opening that had already gone, which no form is left to state.
   *
   * It is held here rather than beside the request because the answer belongs to whichever opening was current
   * when it arrived, and that is what `generation` says: the comparison that keeps a refusal off a draft it is
   * not about is the one that says the refusal has no draft at all. Carried across an open and a close, because
   * a refusal nobody has been told about yet is not answered by the reader opening the form again.
   */
  readonly refusalToReport: boolean;
}

/** A closed dialog with an empty form, one opening on from whatever it closed. */
function closedAfter(held: CaptureState): CaptureState {
  return {
    isOpen: false,
    draft: emptyDraft(),
    returnFocusTo: held.returnFocusTo,
    generation: held.generation + 1,
    refusedAt: null,
    refusalToReport: held.refusalToReport,
  };
}

export interface CaptureHostProps {
  readonly children: ReactNode;
}

export function CaptureHost({ children }: CaptureHostProps) {
  const areas = useAreas();
  const settings = useSettings();
  const write = useTaskCapture();
  const { report } = useClientNotices();
  const [state, setState] = useState<CaptureState>(() => ({
    isOpen: false,
    draft: emptyDraft(),
    returnFocusTo: null,
    generation: 0,
    refusedAt: null,
    refusalToReport: false,
  }));
  /* THE REQUEST, which outlives the dialog that started it. `isSending` is what disables the control and the ref
   * is the same fact answerable inside a click handler, where the state is one render too late. Both move in
   * `taken` and `released` and nowhere else, so they cannot drift apart. */
  const [isSending, setSending] = useState(false);
  const inFlight = useRef(false);

  const zone = settings.status === "ready" ? settings.data.homeZone : ZONE_BEFORE_SETTINGS;
  const listed = areas.status === "ready" ? areas.data.areas : [];

  /* HELD ACROSS RENDERS, and it can be: opening only sets state, and a state setter is stable. A value rebuilt
   * on every render would redraw every screen reading the context on every keystroke in the form.
   *
   * A DIALOG ALREADY OPEN IS LEFT ALONE. `n` pressed twice, or pressed while the form is open, must not discard
   * what the reader has typed, and the Area a caller names is the one it opens ON rather than a change to a
   * draft in flight. */
  const capture = useMemo<Capture>(
    () => ({
      open: (opening: CaptureOpening = {}) => {
        const wasOn = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        /* NAMED-AS-NULL IS NOT THE SAME AS NOT NAMED. A caller whose control will not survive its own write
         * names one that will, and if the ref it names is empty it means "return to nothing" rather than "fall
         * back to the control I already know is doomed": `??` would have re-admitted the very defect review 46
         * found on the empty backlog's prompt. Unreachable today, because the band renders before the prompt
         * can be pressed, which is why it is stated here rather than left to hold by accident. */
        const returnFocusTo = "returnFocusTo" in opening ? (opening.returnFocusTo ?? null) : wasOn;
        setState((held) =>
          held.isOpen
            ? held
            : {
                isOpen: true,
                draft: emptyDraft(opening.areaId),
                returnFocusTo,
                generation: held.generation + 1,
                refusedAt: null,
                refusalToReport: held.refusalToReport,
              },
        );
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
   * Send the draft, once, on behalf of the opening that asked.
   *
   * The generation is captured before the request and compared after it, so a send whose dialog the reader has
   * dismissed or replaced changes nothing: it neither closes a form the reader is typing into nor states a
   * refusal about a draft that no longer exists.
   *
   * THE LOCK IS RELEASED IN A `finally`, because a lock taken before an `await` and released after it is a lock
   * a rejection keeps for the rest of the session: the form would then refuse every later capture with no way
   * back. Review 46 found this as the fifth continuation, after the four the generation answers.
   *
   * IT IS NOT DRIVEN, AND THAT IS NOT THE SAME AS UNTESTABLE. No production call site can make this reject:
   * `apply` answers a `Problem` rather than throwing, by construction, and the SWR filter-mutate the write ends
   * with resolves even when the re-read fails, which review 46 measured at 500 and at transport failure, with
   * and without a subscriber. A test would have to force a shape the wiring cannot produce, which is the one
   * defect class this epic keeps finding. What the `finally` is for is the day SWR's behaviour changes: if a
   * rejection ever becomes reachable here, drive it by making `write.submit` reject and assert the control is
   * enabled again.
   */
  const submit = async (held: CaptureDraft, generation: number) => {
    if (!taken()) return;

    try {
      const applied = await write.submit(bodyOf(held, deadlineInstantOf(held.deadline, zone)));

      /* FOUR OUTCOMES, AND WHICH OPENING THE SEND BELONGS TO DECIDES BETWEEN THEM. A send whose opening is gone
       * closes nothing and states nothing in the form; what it can still do is report a refusal, because a reader
       * who dismissed the dialog has no other way to learn the task was not accepted. */
      setState((current) => {
        if (current.generation !== generation)
          return applied ? current : { ...current, refusalToReport: true };
        return applied ? closedAfter(current) : { ...current, refusedAt: generation };
      });
    } finally {
      released();
    }
  };

  /* THE OTHER CHANNEL, FOR THE REFUSAL NO FORM IS LEFT TO STATE. It is raised after the commit rather than in the
   * send, because the api's own sentence arrives on the write hook's state: the send's continuation holds whether
   * it was refused and not the words. One send at a time, so the problem standing when the flag is set is that
   * send's. Clearing the flag is this host's business and dismissing the banner is the reader's, which the notice
   * source owns: a notice raised twice replaces whatever stands under its id, so one refused capture is one
   * banner however many times it is reported. */
  useEffect(() => {
    if (!state.refusalToReport || write.problem === null) return;
    report(captureNotSavedNotice(write.problem));
    setState((current) => ({ ...current, refusalToReport: false }));
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
          void submit(state.draft, state.generation);
        }}
        refusals={{ ...refusalsIn(state.draft), ...refusalsFrom(refusal) }}
        returnFocusTo={state.returnFocusTo}
        today={todayIn(zone, Date.now())}
      />
    </CaptureContext.Provider>
  );
}
