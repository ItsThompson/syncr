/* THE ONE CAPTURE THE WHOLE APPLICATION SHARES: the `n` binding, the reads the form needs, and the write.
 *
 * MOUNTED ABOVE THE ROUTE, so `n` opens capture from any screen and a screen that wants a control for it asks
 * this host through `useCapture` rather than mounting a second dialog. One instance is what keeps two forms
 * from holding two drafts of the same task.
 *
 * FOCUS RETURNS TO WHERE THE READER WAS, AND THE ELEMENT IS READ HERE RATHER THAN LEFT TO RADIX. Radix restores
 * focus when it can see the trigger that opened the dialog; a chord has no trigger, and measured in this
 * environment the reader lands on the document body, which is nowhere. So `open` reads `document.activeElement`
 * at the moment it is called, which is inside the keystroke's own handler and the last instant the answer still
 * exists, and hands it to the dialog. Openness is a field rather than the absence of a draft for the same
 * reason: unmounting the dialog tears its focus scope down without closing it, so the return never fires.
 *
 * THE AREAS ARE READ HERE AND NOT IN THE DIALOG. A capture needs an Area and the Area list is where the names
 * are, so the read belongs to the host: the form takes the pairs as a prop and is testable without a fixture.
 * The list is read whether or not the dialog is open, because it is the shell's own read and a reader pressing
 * `n` must not wait for it.
 *
 * THE DRAFT IS DISCARDED WHEN THE DIALOG CLOSES AND KEPT WHILE IT IS REFUSED. A reader whose title was too long
 * has to be able to fix the title, and a reader who just captured a task wants an empty form the next time. */

import { useMemo, useState, type ReactNode } from "react";

import { useAreas } from "../../../api/hooks/useAreas";
import { useTaskCapture } from "../../../api/hooks/useBacklog";
import { useSettings } from "../../../api/hooks/useSettings";
import { useKeyBinding } from "../../../lib/keyboard";
import { todayIn } from "../../../lib/zonedInstant";
import { CAPTURE_KEY } from "../../../ui/domain";
import { CaptureContext, type Capture } from "./captureContext";
import { CaptureDialog } from "./CaptureDialog";
import { captureRefusedNotice, refusalsFrom } from "./refusals";
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

/** Whether the dialog is shown, what the form holds, and where the reader was when it opened. */
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
}

export interface CaptureHostProps {
  readonly children: ReactNode;
}

export function CaptureHost({ children }: CaptureHostProps) {
  const areas = useAreas();
  const settings = useSettings();
  const write = useTaskCapture();
  const [state, setState] = useState<CaptureState>(() => ({
    isOpen: false,
    draft: emptyDraft(),
    returnFocusTo: null,
  }));

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
      open: (areaId?: string) => {
        const wasOn = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setState((held) =>
          held.isOpen ? held : { isOpen: true, draft: emptyDraft(areaId), returnFocusTo: wasOn },
        );
      },
      isAvailable: true,
    }),
    [],
  );

  useKeyBinding({ key: CAPTURE_KEY }, capture.open);

  /* The refusal is forgotten when the dialog closes rather than when it opens, so a reader who was refused and
   * dismissed does not meet the same sentence the next time they capture. A successful write clears it already.
   *
   * The element focus returns to is kept through the close, because Radix reads it while the dialog is closing. */
  const close = () => {
    setState((held) => ({ isOpen: false, draft: emptyDraft(), returnFocusTo: held.returnFocusTo }));
    write.clear();
  };

  const submit = async (held: CaptureDraft) => {
    const applied = await write.submit(bodyOf(held, deadlineInstantOf(held.deadline, zone)));
    if (applied) {
      setState((current) => ({
        isOpen: false,
        draft: emptyDraft(),
        returnFocusTo: current.returnFocusTo,
      }));
    }
  };

  return (
    <CaptureContext.Provider value={capture}>
      {children}
      <CaptureDialog
        areas={listed.map((area) => ({ id: area.id, name: area.name }))}
        canSubmit={isSubmittable(state.draft)}
        draft={state.draft}
        isOpen={state.isOpen}
        onDraftChange={(draft) => setState((held) => ({ ...held, draft }))}
        onOpenChange={(next) => {
          if (!next) close();
        }}
        onSubmit={() => {
          void submit(state.draft);
        }}
        refusal={write.problem === null ? undefined : captureRefusedNotice(write.problem)}
        refusals={{ ...refusalsIn(state.draft), ...refusalsFrom(write.problem) }}
        returnFocusTo={state.returnFocusTo}
        today={todayIn(zone, Date.now())}
      />
    </CaptureContext.Provider>
  );
}
